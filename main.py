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
from webrtc_server import start_webrtc_server, current_stream, state_lock
import subprocess
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from env_setup import initialize_gpio, setup_environment
from polygon_store import PolygonStore

if not initialize_gpio():
    print("❌ CRITICAL: GPIO initialization failed!")
    sys.exit(1)

setup_environment()
polygon_store = PolygonStore("polygons.json")

logger = setup_logger(__name__)

POLYGON_FILE = Path("polygons.json")

# Setup logger and notifier
notifier = SystemdNotifier()

# Global Queues and Events
data_queue = queue.Queue(maxsize=10)
state_light = queue.Queue(maxsize=1)
mqtt_queue = queue.Queue(maxsize=2)
event = Event()
event_light = Event()

# Constants
WIDTH, HEIGHT = 640, 360

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
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
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

def sync_webrtc_camera_list(cam_ids):
    cams = []
    for no in cam_ids:
        polys = polygon_store.get_polygons(no)
        cams.append({
            "id": no,
            "polygons": polys or [
                {"coord": [], "seen": 0, "name": ""},
                {"coord": [], "seen": 0, "name": ""}
            ]
        })
    with state_lock:
        if current_stream.get("selected_cam_id") not in [c["id"] for c in cams]:
            current_stream["selected_cam_id"] = cams[0]["id"] if cams else None
        current_stream["cameras"] = cams


def get_selected_camera_id():
    with state_lock:
        return current_stream.get("selected_cam_id")

def update_rtsp_stream(frames_by_no, camera_id):
    if camera_id and camera_id in frames_by_no:
        frame_data = frames_by_no[camera_id]
        FrameSource.update_frame(frame_data)
        # print(f"Streaming camera ID {camera_id}")
    else:
        FrameSource.update_frame(draw_no_camera_frame('No camera'))

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

def detect_camera_fps(cameras, duration=5):
    start = time.time()
    count = 0
    while time.time() - start < duration:
        frames = cameras.read_frame()
        for f in frames:
            if f is not None:
                count += 1
    elapsed = time.time() - start
    fps = count / elapsed if elapsed > 0 else 0
    return min(fps, 15)

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

        cam_ids_internal = sorted(cameras.cameras.keys())

        cameraNO_by_internal = {}
        if camera_setting and "cameras" in camera_setting and camera_setting["cameras"]:
            # assume order of discovered cams aligns with config order; adjust if you have explicit IDs
            for idx, internal_id in enumerate(cam_ids_internal):
                try:
                    cameraNO_by_internal[internal_id] = camera_setting["cameras"][idx]["cameraNO"]
                except Exception:
                    cameraNO_by_internal[internal_id] = internal_id  # fallback
        else:
            cameraNO_by_internal = {iid: iid for iid in cam_ids_internal}

        logger.info(f"Loaded sensor values: {value_counter}")

        #---------------------- Init -------------------------------------
        box_models = {}
        cam_ids = sorted(cameras.cameras.keys())
        for idx, cam_no in enumerate(cam_ids):
            try:
                model = ModelboxProcess(WIDTH, HEIGHT, value=value_counter[idx])
                box_models[cam_no] = model
                print(f"📦 Model for cam {cam_no} initialized")
            except IndexError:
                logger.warning(f"No value_counter for cam {cam_no}, skipping model init")   
        
        mqtt.set_box_model(model=box_models)

        real_fps = int(detect_camera_fps(cameras))
        print(f"📷 Detected camera FPS: {real_fps}")

        Thread(target=lambda: gstream_rtsp_server.start_realtime_rtsp_server(
            port=8554, fps=real_fps, mount="/stream"
        ), daemon=True).start()
        Thread(target=start_webrtc_server, daemon=True).start()

        spacer = np.full((500, 10, 3), 220, dtype=np.uint8)
        state_light.put(3)

        event.set()

        start_time = time.time()
        recorder = MultiCameraRecorder(cams=cameras, fps=16)
        cameras.apply_config(camera_setting)
          
        call_setting = False
        last_stream_time = 0

        frame_buffer = FrameBuffer()

        while True:
            # ------------------------------ Process Loop ------------------------------ #

            if not mqtt.is_connected():
                call_setting = True
                continue
                                    
            if call_setting:
                # 1) pull latest settings from server
                mqtt.del__cameras()
                api_status = mqtt.set_current_setting()

                # 2) refresh values & camera config from server
                value_counter = mqtt.get_main_values()
                camera_setting = mqtt.get_camera_info()

                # 3) (re)apply camera config to the capture layer
                cameras.apply_config(camera_setting)

                # 4) rebuild box_models to match active cameras / value_counter
                cam_ids = sorted(cameras.cameras.keys())
                num_models = min(len(value_counter), len(cam_ids))
                box_models = {}
                for idx, cam_no in enumerate(cam_ids[:num_models]):
                    model = ModelboxProcess(WIDTH, HEIGHT, value=value_counter[idx])
                    box_models[cam_no] = model
                    print(f"📦 Model for cam {cam_no} re-initialized")

                mqtt.set_box_model(model=box_models)
                logger.info(f"API status: {api_status}")
                call_setting = False

            # --- Sync box_models with current cam_ids ---
            for idx, cam_no in enumerate(cam_ids):
                if cam_no not in box_models:
                    try:
                        val = value_counter[idx] if idx < len(value_counter) else [0, 0]
                        box_models[cam_no] = ModelboxProcess(WIDTH, HEIGHT, value=val)
                        logger.info(f"📦 Model created for new cam {cam_no}")
                    except Exception as e:
                        logger.error(f"❌ Failed to init model for cam {cam_no}: {e}")

            # Remove models for cams that no longer exist
            for stale in list(box_models.keys()):
                if stale not in cam_ids:
                    box_models.pop(stale, None)
                    logger.info(f"🗑️ Removed model for cam {stale}")

            # --- Update polygons for each model ---
            for cam_no, model in box_models.items():
                polygons = polygon_store.get_polygons(cam_no) or []
                model.set_polygons([
                    {"coord": p.get("coord", []),
                    "seen": 0,
                    "name": p.get("name", f"Area-{i+1}")}
                    for i, p in enumerate(polygons)
                ])

            # --- Grab frames ---
            frames = [optimize_frame(f) for f in cameras.read_frame()]
            cam_ids = sorted(cameras.cameras.keys())  # real cameraNOs

            # Build frames_by_no dict
            frames_by_no = {}
            all_frames = []
            for idx, cam_no in enumerate(cam_ids):
                frame = frames[idx] if idx < len(frames) else None
                if frame is not None:
                    frames_by_no[cam_no] = frame
                all_frames.append(frame)

            notifier.notify("WATCHDOG=1")

            # ========= Inference =========
            result_map = {}
            with ThreadPoolExecutor(max_workers=max(2, len(cam_ids))) as executor:
                futures = []
                for idx, cam_no in enumerate(cam_ids):
                    frame = frames[idx] if idx < len(frames) else None
                    model = box_models.get(cam_no)
                    if model is None:
                        continue
                    futures.append(executor.submit(process_frame, frame, model, cam_no))

                for fut in futures:
                    cam_no, frame_tuple, counts, *_ = fut.result()
                    if counts:
                        result_map[cam_no] = counts
                    if frame_tuple is not None:
                        frames_by_no[cam_no] = frame_tuple

            # ========= Structure results as JSON (unchanged) =========
            active_cams = sorted(result_map.keys())
            structured_results = []
            for cam_no in active_cams:
                structured_results.append({
                    "cameraNO": cam_no,
                    "value": result_map[cam_no]
                })
            total = sum(sum(v) for v in result_map.values())
            structured_payload = {
                "cameras": structured_results,
                "total": total
            }

            # --- Reconcile selected_cam_id with actual frames ---
            valid_ids = list(frames_by_no.keys())
            with state_lock:
                if current_stream.get("selected_cam_id") not in valid_ids:
                    current_stream["selected_cam_id"] = valid_ids[0] if valid_ids else None

            sel_id = get_selected_camera_id()

            # --- Update RTSP/WebRTC frame source ---
            if sel_id in frames_by_no:
                FrameSource.latest_raw_frame = frames_by_no[sel_id]
                # print(f"🎥 Streaming camera ID {sel_id}")
            else:
                FrameSource.latest_raw_frame = draw_no_camera_frame("No camera")

            # print("🔎 selected_cam =", current_stream["selected_cam_id"], 
            #     "cam_ids =", cam_ids, 
            #     "frames_by_no keys =", list(frames_by_no.keys()))

            # ========= Send out =========
            data_queue.put({'results': structured_payload, 'images': all_frames})

            # --- Update RTSP stream ---
            selected_camera_id = get_selected_camera_id()
            update_rtsp_stream(frames_by_no, selected_camera_id)

            #-------- Record Video ----------
            recorder.record_video_dict(frames_by_no)

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

        return (camera_index, frame, value, None, None)

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
