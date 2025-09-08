# connection.py

import sys
import os
import logging
import asyncio
import subprocess
import threading
from gpiozero import LED
from typing import Any, Dict, Union
from camera import CameraConnection
from bless import (  # type: ignore
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)
import yaml
import queue
from devicecare import DeviceCare
from sdnotify import SystemdNotifier
from logger_config import setup_logger
import time
from env_setup import initialize_gpio

if not initialize_gpio():
    print("❌ CRITICAL: GPIO initialization failed!")
    sys.exit(1)

initialize_gpio()

# ====== Setup =======
logger = setup_logger(__name__)
notifier = SystemdNotifier()

trigger = asyncio.Event()
shutdown_event = threading.Event()
ble_ready_event = threading.Event()
state_light = queue.Queue()

# Global BLE server reference for proper cleanup
ble_server = None
ble_loop = None
current_pattern = None  # Add this global variable

def light_notification():
    """
    Handle LED blinking based on the state in the queue.
    LED States (Boot-style counting patterns):
    0 = OFF - Success/Complete/Ready
    11 = ON - Camera/QR Scanner Ready and BLE Advertising/Ready
    3 = 3 Blinks + pause - No Camera Detected
    4 = 4 Blinks + pause - Camera searching/reinitializing
    5 = 5 Blinks + pause - WiFi Scanning & WiFi Connecting
    1 = 1 Blinks + pause - Data Received (BLE/QR), Processing
    10 = Continuous Fast Blink - All Errors
    """
    global current_pattern
    PIN = 23  # Pin number for LED

    try:
        led = LED(PIN)
    except Exception as e:
        logger.error(f"Error initializing LED on pin {PIN}: {e}")
        return

    try:
        pattern_thread = None
        
        while not shutdown_event.is_set():
            try:
                state = state_light.get(timeout=1)
                
                # Only change pattern if it's different from current
                if state != current_pattern:
                    current_pattern = state
                    logger.debug(f"LED pattern changed to: {state}")
                    
                    # Stop any background blinking first
                    led.off()
                    time.sleep(0.1)  # Brief pause to ensure LED is off
                    
                    # Start new pattern based on state
                    if state == 0:  # Success - turn off
                        led.off()
                    elif state == 11:  # Camera ready - solid on
                        led.on()
                    elif state == 10:  # Error - continuous fast blink
                        led.blink(on_time=0.1, off_time=0.1, background=True)
                    else:  # Counting patterns (3, 4, 5, 7)
                        # Start counting pattern in background thread
                        pattern_thread = threading.Thread(
                            target=blink_pattern_continuous,
                            args=(led, state),
                            daemon=True
                        )
                        pattern_thread.start()
                    
                state_light.task_done()
                
            except queue.Empty:
                # Send watchdog signal while waiting
                try:
                    notifier.notify("WATCHDOG=1")
                except:
                    pass
            except Exception as e:
                logger.error(f"LED error: {e}")
                time.sleep(1)  # Prevent rapid error loops
    
    finally:
        try:
            led.close()
        except:
            pass

def blink_pattern_continuous(led, pattern_count):
    """Continuously repeat a blink pattern until pattern changes"""
    global current_pattern
    
    # Store the pattern we're supposed to be running
    my_pattern = pattern_count
    
    while not shutdown_event.is_set():
        # Check if we're still the current pattern
        if current_pattern != my_pattern:
            break
            
        try:
            # Ensure LED starts OFF for each cycle
            led.off()
            time.sleep(0.3)
            
            # Blink the specified number of times
            for i in range(pattern_count):
                if shutdown_event.is_set() or current_pattern != my_pattern:
                    break
                    
                led.on()
                time.sleep(0.2)  # Short on time
                led.off()
                time.sleep(0.2)  # Short gap between blinks
            
            # Longer pause before repeating pattern
            pause_time = 0
            while pause_time < 2.0 and not shutdown_event.is_set() and current_pattern == my_pattern:
                time.sleep(0.1)
                pause_time += 0.1
                
        except Exception as e:
            logger.error(f"LED pattern error: {e}")
            break

def read_request(characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
    try:
        logger.debug(f"Reading {characteristic.value}")
        return characteristic.value if characteristic.value else bytearray(b"")
    except Exception as e:
        logger.error(f"BLE read error: {e}")
        return bytearray(b"")

def write_request(characteristic: BlessGATTCharacteristic, value: Any, **kwargs):
    try:
        if not value:
            logger.warning("Empty value received in write_request")
            return
            
        characteristic.value = value
        logger.debug(f"Char value set to {characteristic.value}")
        
        # 7 blinks - data received, processing
        state_light.put(1)
        
        # Process the received data
        data_str = bytearray(value).decode('utf-8', errors='ignore').strip()
        logger.info(f"Received BLE data: {data_str}")
        
        # Parse the data
        parts = data_str.split(",")
        if len(parts) < 3:
            logger.error(f"Invalid data format. Expected 3 parts, got {len(parts)}")
            state_light.put(10)  # Error - continuous fast blink
            return
            
        ssid = parts[0][5:].strip() if parts[0].startswith("SSID:") else parts[0].strip()
        wifi_password = parts[1][9:].strip() if parts[1].startswith("Password:") else parts[1].strip()
        key_config = parts[2][4:].strip() if parts[2].startswith("Key:") else parts[2].strip()

        logger.info(f"Parsed - SSID: {ssid}, Password: {'*' * len(wifi_password)}, Key: {key_config[:8]}...")

        # If ethernet is connected, save config directly
        if DeviceCare.is_eth0_connected:
            logger.info("Ethernet connected, saving config directly")
            _save_config(ssid, wifi_password, key_config)
            trigger.set()
            return

        # 5 blinks - WiFi scanning & connecting
        state_light.put(5)
        
        # Check if WiFi network is available
        try:
            check_list_wifi = subprocess.check_output(
                ["nmcli", "-t", "-f", "SSID", "dev", "wifi"], 
                timeout=10, 
                universal_newlines=True
            )
            logger.debug(f"Available WiFi networks:\n{check_list_wifi}")
        except subprocess.TimeoutExpired:
            logger.error("WiFi scan timeout")
            state_light.put(10)  # Error - continuous fast blink
            return
        except Exception as e:
            logger.error(f"WiFi scan error: {e}")
            state_light.put(10)  # Error - continuous fast blink
            return

        if ssid in check_list_wifi:
            logger.info(f"SSID {ssid} found, attempting connection")
            
            if connect_wifi_retry(ssid, wifi_password):
                _save_config(ssid, wifi_password, key_config)
                trigger.set()
                return
            else:
                logger.error("WiFi connection failed after retries")
                state_light.put(10)  # Error - continuous fast blink
        else:
            logger.warning(f"SSID {ssid} not found in available networks")
            state_light.put(10)  # Error - continuous fast blink
            
    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error in write_request: {e}")
        state_light.put(10)  # Error - continuous fast blink
    except Exception as e:
        logger.error(f"BLE write_request failed: {e}")
        state_light.put(10)  # Error - continuous fast blink

def _save_config(ssid, password, key_from_server):
    try:
        with open("config.yaml", "r") as file:
            data = yaml.safe_load(file)

        info = data['Device']
        info['key_from_server'] = key_from_server
        info['wifi']['status'] = True
        info['wifi']['SSID'] = ssid
        info['wifi']['password'] = password if password else None

        with open("config.yaml", "w") as file:
            yaml.dump(data, file, default_flow_style=False, allow_unicode=True)

        logger.info("Config updated successfully")
        state_light.put(0)  # Success - LED OFF
        
    except Exception as e:
        logger.error(f"Config save error: {e}")
        state_light.put(10)  # Error - continuous fast blink

def is_internet_connected(timeout=5):
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), "8.8.8.8"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("Internet connectivity check timeout")
        return False
    except Exception as e:
        logger.error(f"Internet check error: {e}")
        return False

def connect_wifi_retry(ssid, password, max_retries=3):
    for attempt in range(max_retries):
        if shutdown_event.is_set():
            return False
            
        logger.info(f"WiFi connection attempt {attempt+1}/{max_retries} for SSID: {ssid}")
        
        # Keep 5 blinks - WiFi scanning & connecting
        state_light.put(5)

        try:
            # First, disconnect from any existing WiFi
            subprocess.run(["nmcli", "dev", "disconnect", "wlan0"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            time.sleep(2)
            
            # Connect to new WiFi
            cmd = ["nmcli", "dev", "wifi", "connect", ssid, "password", password]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            
            if result.returncode == 0:
                logger.info("WiFi connection command successful, checking internet...")
                # Wait a bit for connection to establish
                time.sleep(5)
                
                if is_internet_connected():
                    logger.info("Internet connection confirmed")
                    return True
                else:
                    logger.warning(f"Attempt {attempt+1}: WiFi connected but no internet")
                    state_light.put(10)  # Error - continuous fast blink
            else:
                logger.error(f"WiFi connection failed: {result.stderr}")
                state_light.put(10)  # Error - continuous fast blink
                
        except subprocess.TimeoutExpired:
            logger.error(f"Attempt {attempt+1}: WiFi connection timeout")
            state_light.put(10)  # Error - continuous fast blink
        except Exception as e:
            logger.error(f"Attempt {attempt+1}: WiFi connection error: {e}")
            state_light.put(10)  # Error - continuous fast blink

        if attempt < max_retries - 1:
            time.sleep(5)  # Wait before retry

    logger.error("All WiFi connection attempts failed")
    state_light.put(10)  # Error - continuous fast blink
    return False

async def run_ble_server_async(loop):
    global ble_server
    
    try:
        trigger.clear()

        gatt: Dict = {
            "A07498CA-AD5B-474E-940D-16F1FBE7E8CD": {
                "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B": {
                    "Properties": (
                        GATTCharacteristicProperties.read
                        | GATTCharacteristicProperties.write
                        | GATTCharacteristicProperties.indicate
                    ),
                    "Permissions": (
                        GATTAttributePermissions.readable
                        | GATTAttributePermissions.writeable
                    ),
                    "Value": bytearray(b"ready"),
                }
            },
            "5c339364-c7be-4f23-b666-a8ff73a6a86a": {
                "bfc0c92f-317d-4ba9-976b-cc11ce77b4ca": {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(b"\x69"),
                }
            },
        }

        ble_server = BlessServer(name="Modela AiCam-BT", loop=loop)
        ble_server.read_request_func = read_request
        ble_server.write_request_func = write_request
        
        await ble_server.add_gatt(gatt)
        await ble_server.start()
        
        logger.info("BLE server started and advertising")
        ble_ready_event.set()
        state_light.put(3)  # 3 blinks - BLE advertising/ready

        # Wait for trigger or shutdown
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(trigger.wait(), timeout=1.0)
                break
            except asyncio.TimeoutError:
                continue

        if not shutdown_event.is_set():
            logger.info("Configuration received, updating characteristic...")
            
            # Update characteristic to indicate success
            try:
                characteristic = ble_server.get_characteristic("51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B")
                if characteristic:
                    characteristic.value = bytearray(b"success")
                    ble_server.update_value("A07498CA-AD5B-474E-940D-16F1FBE7E8CD", 
                                          "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B")
            except Exception as e:
                logger.error(f"Error updating characteristic: {e}")

            await asyncio.sleep(3)

    except Exception as e:
        logger.error(f"BLE server error: {e}")
    
    finally:
        logger.info("Stopping BLE server...")
        if ble_server:
            try:
                await ble_server.stop()
            except Exception as e:
                logger.error(f"Error stopping BLE server: {e}")
        shutdown_event.set()

def run_ble_server():
    global ble_loop
    logger.info("Starting BLE server thread")
    
    try:
        ble_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ble_loop)
        ble_loop.run_until_complete(run_ble_server_async(ble_loop))
    except Exception as e:
        logger.error(f"BLE server thread error: {e}")
    finally:
        logger.info("BLE server thread exiting")

def run_camera():
    import cv2
    import re
    from pyzbar.pyzbar import decode

    device_index = None
    camera = None

    try:
        while device_index is None and not shutdown_event.is_set():
            logger.info("Searching for camera...")
            state_light.put(3)  # 3 blinks - no camera detected
            device_index = CameraConnection.find_working_camera()
            if device_index is None:
                time.sleep(5)
        
        if shutdown_event.is_set():
            return
            
        # Camera found
        state_light.put(11)  # LED ON - camera/QR scanner ready
        
        if shutdown_event.is_set():
            return
            
        camera = cv2.VideoCapture(device_index)
        if not camera.isOpened():
            logger.error("Failed to open camera")
            return
            
        # Set camera properties for better stability
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        camera.set(cv2.CAP_PROP_FPS, 15)
        
        logger.info("QR Code reader started")
        frame_count = 0
        
        while not shutdown_event.is_set():
            ret, frame = camera.read()
            
            if not ret or frame is None:
                logger.warning("Failed to read frame, reinitializing camera...")
                state_light.put(4)  # 4 blinks - camera searching/reinitializing
                camera.release()
                device_index = None
                
                # Find camera again
                while device_index is None and not shutdown_event.is_set():
                    logger.info("Re-scanning for camera...")
                    state_light.put(4)  # 4 blinks - camera searching/reinitializing
                    device_index = CameraConnection.find_working_camera()
                    if device_index is None:
                        time.sleep(3)
                
                if shutdown_event.is_set():
                    break
                    
                # Camera found again
                state_light.put(11)  # LED ON - camera ready
                
                if shutdown_event.is_set():
                    break
                    
                camera = cv2.VideoCapture(device_index)
                if not camera.isOpened():
                    logger.error("Failed to reopen camera")
                    break
                    
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                camera.set(cv2.CAP_PROP_FPS, 15)
                continue

            # Process every 5th frame to reduce CPU load
            frame_count += 1
            if frame_count % 5 != 0:
                continue

            try:
                decoded_objects = decode(frame)
                for obj in decoded_objects:
                    data = obj.data.decode("utf-8", errors='ignore')
                    logger.info(f"QR Code detected: {data}")
                    state_light.put(1)  # 7 blinks - processing QR data

                    ssid = _extract_field(data, "SSID")
                    password = _extract_field(data, "Password") or ""
                    key = _extract_field(data, "Key")

                    if not ssid or not key:
                        logger.error("Invalid QR code format - missing SSID or Key")
                        state_light.put(10)  # Error - continuous fast blink
                        continue

                    if DeviceCare.is_eth0_connected:
                        logger.info("Ethernet connected, saving QR config")
                        _save_config(ssid, password, key)
                        shutdown_event.set()
                        return

                    # 5 blinks - WiFi scanning & connecting
                    state_light.put(5)
                    
                    # Check WiFi availability
                    try:
                        wifi_list = subprocess.check_output(
                            ["nmcli", "-t", "-f", "SSID", "dev", "wifi"], 
                            timeout=10, universal_newlines=True
                        )
                        
                        if ssid in wifi_list:
                            if connect_wifi_retry(ssid, password):
                                _save_config(ssid, password, key)
                                shutdown_event.set()
                                return
                            else:
                                logger.error("QR WiFi connection failed")
                                state_light.put(10)  # Error - continuous fast blink
                        else:
                            logger.warning(f"QR SSID {ssid} not found")
                            state_light.put(10)  # Error - continuous fast blink
                            
                    except subprocess.TimeoutExpired:
                        logger.error("WiFi scan timeout during QR processing")
                        state_light.put(10)  # Error - continuous fast blink
                        
            except Exception as e:
                logger.error(f"QR processing error: {e}")
                state_light.put(10)  # Error - continuous fast blink

            # Brief pause to prevent excessive CPU usage
            time.sleep(0.1)

    except Exception as e:
        logger.error(f"Camera thread error: {e}")
    finally:
        if camera:
            try:
                camera.release()
            except:
                pass
        logger.info("Camera thread exiting")

def _extract_field(data: str, field: str) -> Union[str, None]:
    import re
    try:
        match = re.search(rf"{field}:([^,]+)", data)
        return match.group(1).strip() if match else None
    except Exception as e:
        logger.error(f"Error extracting field {field}: {e}")
        return None

def run_watchdog():
    while not shutdown_event.is_set():
        try:
            notifier.notify("WATCHDOG=1")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            time.sleep(5)

def main():
    try:
        notifier.notify("READY=1")
        state_light.put(3)  # 3 blinks - system starting, no camera detected yet

        threads = [
            threading.Thread(target=run_ble_server, daemon=True, name="BLE-Server"),
            threading.Thread(target=run_camera, daemon=True, name="Camera-QR"),
            threading.Thread(target=run_watchdog, daemon=True, name="Watchdog"),
            threading.Thread(target=light_notification, name="LED-Control")
        ]

        for t in threads:
            t.start()
            logger.info(f"Started thread: {t.name}")

        # Wait for BLE to be ready
        if ble_ready_event.wait(timeout=30):
            logger.info("BLE server is ready")
        else:
            logger.error("BLE server failed to start within timeout")

        # Wait for shutdown
        shutdown_event.wait()
        
        logger.info("Shutdown signal received, cleaning up...")
        
        # Give threads time to cleanup
        time.sleep(2)
        
        logger.info("Setup complete. Exiting...")
        
    except Exception as e:
        logger.error(f"Main thread error: {e}")
    finally:
        shutdown_event.set()
        sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down...")
        shutdown_event.set()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        shutdown_event.set()
        sys.exit(1)
