import cv2
import numpy as np
import time
import math
import os
import threading
import queue
from logger_config import setup_logger

logger = setup_logger(__name__)

class LowLatencyIPCamera:
    """Dedicated class for ultra-low latency IP camera handling"""
    
    def __init__(self, rtsp_url, camera_no, name, target_fps=15):
        self.rtsp_url = rtsp_url
        self.camera_no = camera_no
        self.name = name
        self.target_fps = target_fps
        self.cap = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.capture_thread = None
        self.frame_count = 0
        self.last_fps_check = time.time()
        
    def start(self):
        """Initialize and start the low-latency capture"""
        try:
            # Initialize with aggressive low-latency settings
            self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            
            if not self.cap.isOpened():
                logger.error(f"Failed to open IP camera {self.rtsp_url}")
                return False
            
            # CRITICAL: Ultra-low latency settings
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimum possible buffer
            self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            
            # Try to set additional low-latency properties
            try:
                # Use H.264 for faster decoding if available
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H','2','6','4'))
            except:
                pass
                
            # Set target resolution
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1080)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            # Start aggressive frame grabbing thread
            self.running = True
            self.capture_thread = threading.Thread(target=self._aggressive_capture, daemon=True)
            self.capture_thread.start()
            
            logger.info(f"Low-latency IP camera {self.camera_no} started")
            return True
            
        except Exception as e:
            logger.error(f"Error starting IP camera {self.camera_no}: {e}")
            return False
    
    def _aggressive_capture(self):
        """Aggressively capture frames, always keeping only the latest"""
        consecutive_failures = 0
        max_failures = 30  # Allow 30 consecutive failures before giving up
        
        while self.running:
            try:
                # Skip buffered frames by grabbing multiple times
                for _ in range(3):  # Skip 3 buffered frames
                    if not self.cap.grab():
                        consecutive_failures += 1
                        break
                else:
                    consecutive_failures = 0
                
                if consecutive_failures > max_failures:
                    logger.error(f"Too many consecutive failures for camera {self.camera_no}")
                    break
                
                # Retrieve the actual frame
                ret, frame = self.cap.retrieve()
                
                if ret and frame is not None and frame.size > 0:
                    # Resize if needed
                    if frame.shape[:2] != (720, 1080):
                        frame = cv2.resize(frame, (1080, 720))

                    # Ensure contiguous memory layout
                    if not frame.flags['C_CONTIGUOUS']:
                        frame = np.ascontiguousarray(frame)
                    
                    # Update latest frame atomically
                    with self.frame_lock:
                        self.latest_frame = frame.copy()
                        self.frame_count += 1
                    
                    # FPS monitoring
                    current_time = time.time()
                    if current_time - self.last_fps_check >= 5.0:  # Check every 5 seconds
                        fps = self.frame_count / (current_time - self.last_fps_check)
                        logger.debug(f"Camera {self.camera_no} actual FPS: {fps:.1f}")
                        self.frame_count = 0
                        self.last_fps_check = current_time
                        
                else:
                    consecutive_failures += 1
                    time.sleep(0.01)  # Brief pause on failure
                    
            except Exception as e:
                logger.error(f"Frame capture error for camera {self.camera_no}: {e}")
                consecutive_failures += 1
                time.sleep(0.01)
    
    def read(self):
        """Get the latest frame"""
        with self.frame_lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
            return False, None
    
    def stop(self):
        """Stop the camera capture"""
        self.running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()

class CameraConnection:
    MAX_CAMERAS = 2

    def __init__(self, width: int = 1080, height: int = 720) -> None:
        self.size_width = width
        self.size_height = height
        self.cameras = []
        self.Amount_cameras = 0
        self.reset_camera = False
        self.cameras_connected = []
        self.ip_camera_threads = {}  # Track IP camera threads

    # ------------- Config ---------------
    def set_width(self, width: int) -> None:
        self.size_width = width

    def set_height(self, height: int) -> None:
        self.size_height = height

    def get_width(self) -> int:
        return self.size_width

    def get_height(self) -> int:
        return self.size_height
    
    def get_Amount_cameras(self) -> int:
        return self.Amount_cameras

    # ------------- Camera Handling -------------

    def probe_capture_indexes(self, max_index=10):
        ok = []
        for i in range(max_index):
            dev = f"/dev/video{i}"
            if not os.path.exists(dev):
                continue
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                continue
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size_width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size_height)
                # MJPG for lower latency if supported
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                # CRITICAL: Set buffer size to 1 for USB cameras too
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None and frame.size > 0:
                ok.append(i)
        logger.info(f"Usable capture indexes: {ok}")
        return ok

    def set_cameras_on_device(self):
        self.cameras_connected = self.probe_capture_indexes(max_index=10)
        logger.info(f"Discovered usable cameras: {self.cameras_connected}")

    def _set_common_props(self, cap: cv2.VideoCapture):
        try:
            # Set resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size_height)
            
            # CRITICAL: Minimum buffer size for all cameras
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Use MJPG format for better performance on USB cameras
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            
            # Optimize exposure and gain for speed
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Reduce auto-exposure time
            cap.set(cv2.CAP_PROP_EXPOSURE, -6)  # Set fixed exposure for speed
            
            # Set target FPS
            cap.set(cv2.CAP_PROP_FPS, 15)
            
        except Exception as e:
            logger.warning(f"Could not set camera properties: {e}")

    def apply_config(self, camera_setting: dict):
        try:
            self.del_all_camera()
            self.set_cameras_on_device()
            detected = set(self.get_cameras_on_device() or [])
            used = set()
            cams = (camera_setting or {}).get('cameras', [])
            if isinstance(cams, dict):
                cams = [cams]
            elif not isinstance(cams, list):
                cams = []
            for cam in cams:
                ctype = (cam.get('type') or '').lower()
                if ctype in ('webcam', 'usb', 'pi', 'pi_cam'):
                    idx = cam.get('index')
                    if idx is None or idx not in detected or idx in used:
                        candidate = next((d for d in detected if d not in used), None)
                        if candidate is None:
                            logger.warning("No free detected webcam index available; skipping camera %s", cam)
                            continue
                        idx = candidate
                    payload = {**cam, 'index': idx}
                    self.add_webcam_pi_camera(payload)
                    if len(self.cameras) > 0 and self.cameras[-1].get('index') == idx:
                        used.add(idx)
                elif ctype in ('ip', 'rtsp', 'http'):
                    self.add_ip_camera_optimized(cam)  # Use optimized version
                else:
                    logger.warning(f"Unknown camera type '{ctype}' for {cam}")
            if self.Amount_cameras == 0:
                logger.error("apply_config finished but no camera opened.")
        except Exception as e:
            logger.error(f"apply_config error: {e}", exc_info=True)

    def read_frame(self) -> list:
        frames = []
        connected = False
        self.cameras.sort(key=lambda x: x["cameraNO"])
        
        for cam in self.cameras:
            if cam is not None:
                try:
                    # Check if this is an optimized IP camera
                    if "ip_camera_obj" in cam:
                        ret, frame = cam["ip_camera_obj"].read()
                    else:
                        # Traditional camera handling with optimizations
                        cap = cam['cam']
                        
                        # For regular IP cameras, still do frame skipping but less aggressive
                        if "ip" in cam.get("name", "").lower() or cam.get("ip"):
                            # Skip only 1 frame for better balance of latency vs reliability
                            cap.grab()
                        
                        ret, frame = cap.read()
                    
                    if not ret or frame is None or frame.size == 0:
                        logger.warning(f"Invalid frame from camera {cam.get('cameraNO')}")
                        continue
                        
                    # Resize only if necessary
                    if frame.shape[:2] != (self.size_height, self.size_width):
                        frame = cv2.resize(frame, (self.size_width, self.size_height))
                        
                    # Ensure contiguous memory layout
                    if not frame.flags['C_CONTIGUOUS']:
                        frame = np.ascontiguousarray(frame)
                        
                    frames.append(frame)
                    connected = True
                    
                except Exception as e:
                    logger.error(f"Error reading from camera {cam.get('cameraNO')}: {e}")
                    continue
                
        if not connected:
            logger.error("No connected camera.")
            
        return frames

    def add_webcam_pi_camera(self, camera: dict):
        if self.Amount_cameras == self.MAX_CAMERAS:
            logger.warning("Maximum camera limit reached.")
            return
        try:
            index_map = {1: 0, 2: 2}
            cameraNO = camera["cameraNO"]
            camera_index = camera.get("index", index_map.get(cameraNO))
            if camera_index is None:
                logger.warning(f"No index provided or mapped for cameraNO {cameraNO}")
                return
            if any(cam["cameraNO"] == cameraNO or cam.get("index") == camera_index for cam in self.cameras):
                logger.info(f"Camera {cameraNO} or index {camera_index} already added.")
                return
                
            cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
            
            if not cap.isOpened():
                logger.warning(f"Cannot open webcam at index {camera_index}")
                return
                
            self._set_common_props(cap)
            
            # Test frame read
            ret, test_frame = cap.read()
            if not ret or test_frame is None:
                logger.error(f"Camera {camera_index} opened but cannot read frames")
                cap.release()
                return
            else:
                logger.info(f"Camera {camera_index} test frame shape: {test_frame.shape}")
            
            self.cameras.append({
                "cameraNO": cameraNO,
                "cam": cap,
                "name": camera["name"],
                "index": camera_index
            })
            self.Amount_cameras += 1
            logger.info(f"Webcam {cameraNO} added from index {camera_index}")
        except Exception as e:
            logger.error(f"Error adding webcam: {e}", exc_info=True)

    def add_ip_camera_optimized(self, camera: dict):
        """Add IP camera with ultra-low latency optimization"""
        if self.Amount_cameras >= self.MAX_CAMERAS:
            logger.warning("Maximum camera limit reached.")
            return
            
        try:
            camera_no = camera["cameraNO"]
            rtsp_url = camera["ip"]
            name = camera["name"]
            
            # Create optimized IP camera instance
            ip_cam = LowLatencyIPCamera(rtsp_url, camera_no, name)
            
            if ip_cam.start():
                # Add to cameras list with special marker
                self.cameras.append({
                    "cameraNO": camera_no,
                    "name": name,
                    "ip": rtsp_url,
                    "ip_camera_obj": ip_cam  # Special marker for optimized handling
                })
                
                # Track the IP camera thread
                self.ip_camera_threads[camera_no] = ip_cam
                
                self.Amount_cameras += 1
                logger.info(f"Optimized IP camera {camera_no} added successfully")
            else:
                logger.error(f"Failed to start optimized IP camera {camera_no}")
                
        except Exception as e:
            logger.error(f"Error adding optimized IP camera: {e}", exc_info=True)

    def add_ip_camera(self, camera: dict):
        """Fallback method - use optimized version instead"""
        logger.info("Using optimized IP camera method")
        self.add_ip_camera_optimized(camera)

    def del_camera(self, cameras_info=None):
        if cameras_info is None:
            return
        camera_ids = {cam["cameraNO"] for cam in cameras_info}
        index = next((i for i, cam in enumerate(self.cameras)
                      if cam and cam["cameraNO"] not in camera_ids), None)
        if index is not None:
            cam = self.cameras[index]
            
            # Stop optimized IP camera if applicable
            if "ip_camera_obj" in cam:
                cam["ip_camera_obj"].stop()
                if cam["cameraNO"] in self.ip_camera_threads:
                    del self.ip_camera_threads[cam["cameraNO"]]
            else:
                cam["cam"].release()
                
            del self.cameras[index]
            self.Amount_cameras -= 1
            logger.info("Camera removed.")
            if self.Amount_cameras == 0:
                self.reset_camera = True

    def del_all_camera(self):
        for cam in self.cameras:
            if cam is not None:
                # Stop optimized IP camera if applicable
                if "ip_camera_obj" in cam:
                    cam["ip_camera_obj"].stop()
                else:
                    cam["cam"].release()
                    
        # Clear IP camera threads
        self.ip_camera_threads.clear()
        
        self.cameras.clear()
        self.Amount_cameras = 0

    def get_cameras_on_device(self):
        return self.cameras_connected

    # ---------- Frame Utility ----------
    def stack_frames_grid(self, frames, spacer=None):
        if not frames:
            return None
        frames = [f for f in frames if f is not None]
        if not frames:
            return None
        try:
            num = len(frames)
            cols = math.ceil(math.sqrt(num))
            rows = math.ceil(num / cols)
            h_ref, w_ref = frames[0].shape[:2]
            frames_resized = [cv2.resize(f, (w_ref, h_ref)) for f in frames]
            while len(frames_resized) < rows * cols:
                frames_resized.append(np.zeros_like(frames_resized[0]))
            row_images = []
            for i in range(0, len(frames_resized), cols):
                row = frames_resized[i:i+cols]
                if spacer is not None:
                    spacer_h = cv2.resize(spacer, (spacer.shape[1], h_ref))
                    row_img = np.hstack([img if j == len(row) - 1 else np.hstack((img, spacer_h))
                                         for j, img in enumerate(row)])
                else:
                    row_img = np.hstack(row)
                row_images.append(row_img)
            if spacer is not None:
                spacer_v = cv2.resize(spacer, (row_images[0].shape[1], spacer.shape[0]))
                full_image = row_images[0]
                for r in row_images[1:]:
                    full_image = np.vstack((full_image, spacer_v, r))
            else:
                full_image = np.vstack(row_images)
            return full_image
        except Exception as e:
            logger.error(f"Error stacking frames: {e}", exc_info=True)
            return None

    @staticmethod
    def find_working_camera(max_index=10):
        for i in range(max_index):
            device_path = f"/dev/video{i}"
            if os.path.exists(device_path):
                cap = cv2.VideoCapture(device_path)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        print(f"Using camera at: {device_path}")
                        return device_path
        print("No usable camera found.")
        return None