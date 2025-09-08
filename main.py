#!/usr/bin/env python3
#---------------------------------------------UPDATE#---------------------------------------------#
'''
    UPDATE environnment: if any update except the code please write here
'''
#---------------------------------------------UPDATE#---------------------------------------------#

#main.py 

import gstream_rtsp_server 
import os
import cv2
import time
import sys
import queue
import numpy as np
from threading import Thread,Event
import yaml
import subprocess
from gpiozero import LED
from logger_config import setup_logger
from mq_connector import Mqtt_Connect
from button_light import Button_Action
from camera import CameraConnection
from devicecare import DeviceCare
from boxprocess import ModelboxProcess
from datetime import datetime
from record_v import MultiCameraRecorder
from sdnotify import SystemdNotifier
from gstream_rtsp_server import FrameSource
from webrtc_server import start_webrtc_server, current_stream
import subprocess
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from env_setup import initialize_gpio, setup_environment

if not initialize_gpio():
    print("❌ CRITICAL: GPIO initialization failed!")
    sys.exit(1)

setup_environment()

logger = setup_logger(__name__)

POLYGON_FILE = Path("polygons.json")

# Setup logger and notifier
notifier = SystemdNotifier()

class SmartQueue:
    def __init__(self, maxsize=5):
        self.queue = queue.Queue(maxsize=maxsize)
    
    def put(self, item, block=True, timeout=None):
        """Blocking put that drops oldest item if full"""
        try:
            self.queue.put(item, block=block, timeout=timeout)
        except queue.Full:
            try:
                self.queue.get_nowait()  # Remove oldest item
                self.queue.put(item, block=False)  # Add new item
            except queue.Empty:
                pass
    
    def put_nowait(self, item):
        """Non-blocking put that drops oldest item if full"""
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(item)
            except queue.Empty:
                pass
    
    def get(self, timeout=None):
        return self.queue.get(timeout=timeout)
    
    def get_nowait(self):
        return self.queue.get_nowait()

# Global Queues and Events
data_queue = queue.Queue(maxsize=10)
state_light = queue.Queue(maxsize=1)
mqtt_queue = queue.Queue(maxsize=2)
event = Event()
event_light = Event()

# Constants
WIDTH, HEIGHT = 1080, 720


# Connect with server
def result_sending():
    event.wait()
    try:
        mqtt = mqtt_queue.get(timeout=10)
    except queue.Empty:
        logger.error("Timeout: No MQTT instance available.",exc_info=True)
        return
    
    counter_reboot = 0
    status_connection_light = False
    last_time = time.time()
    last_connection = time.time()
    
    # Send the result to MQTT
    while True:
        notifier.notify("WATCHDOG=1")
        
        if not mqtt.is_connected():
            state_light.put(2)
            status_connection_light = True
            logger.warning("Wait for connection")
            if counter_reboot == 150:
                DeviceCare.reboot_device()
            counter_reboot += 1
            time.sleep(1)
            continue
        
        
        if status_connection_light:
            state_light.put(3)
            status_connection_light = False
            
        try:
            information = data_queue.get(timeout=5)
        except queue.Empty:
            continue
        counter_reboot = 0
        
        # print(information)

        if time.time() - last_connection >= 30:
            mqtt.Connection_status()
            last_connection = time.time()
        if time.time() - last_time >= 3:
            try:
                pass
                mqtt.client_publish(information['results'], information['images'])
                # mqtt.send_notification(information['images'],
                #                     information['results'])
            except Exception as e:
                logger.error(f"some error in publish!,{e}",exc_info=True)
            last_time = time.time()
        
        time.sleep(0.2)

# Reset button
def reset():
    BUTTON_PIN = 17 # Pin num for reset button

    # Creat the reset button instance
    btn = Button_Action(BUTTON_PIN)

    # Start the reset button action
    btn.reset_mode(state_light)

# Notify the state by 
def light_notification():
    event_light.wait()
    PIN = 23    # Pin num for red LED
    led = LED(PIN)
    while True:
        try:
            state = state_light.get(timeout=1)  # Wait for a new state with timeout
            if state == 1:  # reset
                led.blink(on_time=0.1,off_time=0.1,background = True) #1
            if state ==2:   # no connection
                led.blink(on_time=0.5,off_time=0.05,background = True) #3
            if state ==3:   # connection successful
                led.on() 
            state_light.task_done()
            
        except queue.Empty:
            pass  # No new state, continue looping

def wait_for_network(timeout=150):
    """รอการเชื่อมต่อเครือข่าย"""
    time_out = 0
    while True:
        notifier.notify("WATCHDOG=1")
        if DeviceCare.is_eth0_connected():
            logger.info("Connected via Ethernet")
            return True

        status_internet = DeviceCare.Connection_wifi()
        if status_internet and DeviceCare.is_internet_connected() and DeviceCare.is_wifi_connected():
            logger.info("Connected via WiFi")
            return True
        elif not status_internet:
            logger.warning("No wifi connection")
        else:
            logger.warning("Connected to WiFi but no Internet")

        time_out += 1
        if time_out == timeout:
            logger.critical("Connection timeout. Rebooting.")
            DeviceCare.reboot_device()
        time.sleep(2)

def draw_no_camera_frame(text):
    frame = np.zeros((720, 1080, 3), dtype=np.uint8)
    cv2.putText(frame, text, (80, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)
    return frame

class FrameBuffer:
    def __init__(self, maxsize=3):
        self.buffer = {}
        self.maxsize = maxsize
    
    def update(self, camera_id, frame):
        if camera_id not in self.buffer:
            self.buffer[camera_id] = {}
        self.buffer[camera_id] = frame
        
    def get(self, camera_id):
        """Get frame from buffer by camera_id"""
        return self.buffer.get(camera_id, {})
    
    def get_all(self):
        """Get all frames in buffer"""
        return self.buffer

def update_rtsp_stream(all_frames, selected_cam_idx, draw_no_camera_frame):
    try:
        if 0 <= selected_cam_idx < len(all_frames) and all_frames[selected_cam_idx] is not None:
            FrameSource.update_frame(all_frames[selected_cam_idx])
        else:
            FrameSource.update_frame(draw_no_camera_frame('No camera'))
    except Exception:
        FrameSource.update_frame(draw_no_camera_frame('Error'))

def load_polygons_from_file(camera_id=0):
    """Load polygons for a given camera id from polygons.json"""
    if not POLYGON_FILE.exists():
        return []
    try:
        with POLYGON_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        cams = data.get("cameras", [])
        for cam in cams:
            if cam.get("id") == camera_id:
                return [p.get("coord", []) for p in cam.get("polygons", []) if p.get("coord")]
    except Exception as e:
        print("⚠️ Failed to load polygons.json:", e)
    return []

def main():
    Thread(target=light_notification, daemon=True).start()
    Thread(target=reset, daemon=True).start()
    Thread(target=result_sending, daemon=True).start()

    #เช็คว่ามีการลงทะเบียนยัง ไม่มีสั่ง shutdown
    if "config.yaml" not in os.listdir():
        logger.warning("The device has not been registered!")
        time.sleep(30)
        os.system("sudo shutdown -h now")

    current_serial = DeviceCare.get_serial()
    with open("config.yaml", "r") as file:
        config = yaml.safe_load(file)

    device = config['Device']
    unlock_device = config['Unlock-Device'] #Bypass เอาไว้ซ่อม

    #เช็คเลขซีเรียลกันโดนย้าย pi
    if device['key_device'] != current_serial:
        if current_serial in unlock_device:
            sys.exit()
        logger.warning("The device is not correct!")
        time.sleep(30)
        DeviceCare.reboot_device()
    
    if not device['wifi']['status'] and not device['key_from_server']:
        subprocess.run(["python", "connection.py"])

    event_light.set()
    state_light.put(2)
    notifier.notify("READY=1")
    time_out = 0

    if not wait_for_network():
        return

    mqtt = None
            
    try:
        cameras = CameraConnection()
        mqtt = Mqtt_Connect(device['type'], device['version'],device['key_from_server'],cameras)
        last_cam = -1

        print(cameras)

        if not mqtt.set_current_setting():
            return

        mqtt_queue.put(mqtt)
        value_counter = mqtt.get_main_values()
        camera_setting = mqtt.get_camera_info()

        print(camera_setting)

        logger.info(f"Loaded sensor values: {value_counter}")
        box_models = []
        for index in range(2):
            model = ModelboxProcess(WIDTH, HEIGHT, value=value_counter[index])
            box_models.append(model)
            print(f"📦 Model {index} initialized")
        
        mqtt.set_box_model(model=box_models)

        Thread(target=gstream_rtsp_server.start_rtsp_server, daemon=True).start()
        Thread(target=start_webrtc_server, daemon=True).start()

        spacer = np.full((500, 10, 3), 220, dtype=np.uint8)
        state_light.put(3)

        event.set()

        start_time = time.time()
        recoder = MultiCameraRecorder(cams=cameras)
        cameras.apply_config(camera_setting)
          
        call_setting = False
        last_stream_time = 0
        stream_interval = 1.0 / 10 

        frame_buffer = FrameBuffer()

        while True:
        # ------------------------------ Process is Here ------------------------------ #
            if not mqtt.is_connected():
                call_setting = True
                continue
                        
            if call_setting:
                mqtt.del__cameras()
                api_status = mqtt.set_current_setting()
                for model in box_models:
                    model.set_new_value(mqtt.get_Data_info())
                logger.info(f"API status: {api_status}")
                call_setting = False

            for cam_id, model in enumerate(box_models):
                polygons = load_polygons_from_file(cam_id)
                model.set_polygons([
                    {"coord": p, "seen": 0, "name": f"Area-{i+1}"} 
                    for i, p in enumerate(polygons)
                ])

            frames = [optimize_frame(f) for f in cameras.read_frame()]
            selected_cam = current_stream["selected_cam"]
            if 0 <= selected_cam < len(frames):
                FrameSource.latest_raw_frame = frames[selected_cam]

            all_frames, results = [], []
            notifier.notify("WATCHDOG=1")

            # =============== New Streaming and Recording data ===================
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = []
                for index, (frame, model) in enumerate(zip(frames, box_models)):
                    if index < len(cameras.cameras) and cameras.cameras[index] is not None:
                        futures.append(executor.submit(process_frame, frame, model, index))
                
                all_frames = [None] * len(cameras.cameras)
                results = [None] * len(cameras.cameras)

                for future in futures:
                    result = future.result()
                    idx, frame_tuple, counts, *_ = result   # ใช้ * เก็บค่าที่เหลือ
                    all_frames[idx] = frame_tuple
                    results[idx] = counts

            # Flatten the list of lists and remove None
            results = [d for sublist in results if sublist for d in sublist]
            total = sum(sum(frame) for frame in results)
            results_with_total = results + [total]

            # recoder.record_video(all_frames)

            # print("Results:", results) 
            # print("All Frames:", all_frames)

            data_queue.put({'results': results_with_total,'images': all_frames})

            # """ 
            # all_frames = [
            # (กล้อง0),
            # (กล้อง1)
            # ] """

            # # Choose which view in the tuple you want to display (0 or 1)
            update_rtsp_stream(all_frames, selected_cam, draw_no_camera_frame)

            # ------------------------------ END ------------------------------ #

    except Exception as e:
        mqtt.loop_stop()
        mqtt.disconnect()
        logger.critical(f"The error is: {e}",exc_info=True)

def process_frame(frame, model, camera_index):
    """Process a single frame in parallel"""
    try:
        if frame is None:
            logger.warning(f"Received None frame for camera {camera_index}")
            return (camera_index, (None, None), [], None, None)
            
        # logger.debug(f"Processing frame for camera {camera_index}: shape={frame.shape}")
        frame, value = model(frame)
        
        # Validate outputs
        if frame is None:
            logger.warning(f"Model returned None frames for camera {camera_index}")

        return (camera_index, frame, [value], None, None)

    except Exception as e:
        logger.error(f"Error processing camera {camera_index}: {e}", exc_info=True)
        return (camera_index, (None, None), [], None, None)

def optimize_frame(frame):
    """Ensure frame is optimized for processing"""  
    if frame is None:
        return None
    # Ensure contiguous and correct data type
    if not frame.flags['C_CONTIGUOUS']:
        frame = np.ascontiguousarray(frame)
    # Use uint8 for memory efficiency
    if frame.dtype != np.uint8:
        frame = frame.astype(np.uint8)
    return frame

def monitor_performance():
    import psutil
    while True:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        print(f"CPU: {cpu_percent}% | RAM: {memory.percent}% | "
              f"Available: {memory.available / 1024 / 1024:.1f}MB")
        time.sleep(5)

if __name__ == "__main__":
    # Add to main():
    Thread(target=monitor_performance, daemon=True).start()
    main()
