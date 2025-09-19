#camera.py
import cv2
import numpy as np
import time
import math
import os
import threading
import queue
from logger_config import setup_logger
from polygon_store import PolygonStore

polygon_store = PolygonStore("polygons.json")

logger = setup_logger(__name__)

class LowLatencyIPCamera:
    """Dedicated class for ultra-low latency IP camera handling"""

    def __init__(self, rtsp_url, camera_no, name, target_fps=15, use_gst=False):
        self.rtsp_url = rtsp_url
        self.camera_no = camera_no
        self.name = name
        self.target_fps = target_fps
        self.use_gst = use_gst

        self.cap = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.capture_thread = None
        self.frame_count = 0
        self.last_fps_check = time.time()

        # CRITICAL: Frame timing
        self.frame_interval = 1.0 / target_fps
        self.last_frame_time = 0

    def start(self):
        """Initialize and start the low-latency capture"""
        try:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                "rtsp_transport;tcp|max_delay;0|fflags;nobuffer"
            )

            # Or append URL options directly
            if "?" not in self.rtsp_url:
                self.rtsp_url += "?fflags=nobuffer&flags=low_delay&max_delay=0"

            self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

            if not self.cap.isOpened():
                print(f"❌ Failed to open IP camera {self.rtsp_url}")
                return False

            # CRITICAL: Buffer & FPS
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

            self.running = True
            self.capture_thread = threading.Thread(
                target=self._controlled_capture, daemon=True
            )
            self.capture_thread.start()

            print(f"✅ Camera {self.camera_no} started at {self.target_fps} FPS (GStreamer={self.use_gst})")
            return True

        except Exception as e:
            print(f"Error starting IP camera {self.camera_no}: {e}")
            return False

    def _controlled_capture(self):
        """Controlled capture at exact FPS intervals"""
        consecutive_failures = 0
        max_failures = 30

        while self.running:
            try:
                now = time.time()
                if now - self.last_frame_time < self.frame_interval:
                    time.sleep(0.001)
                    continue

                ret, frame = self.cap.read()
                if not ret or frame is None or frame.size == 0:
                    consecutive_failures += 1
                    if consecutive_failures > max_failures:
                        print(f"❌ Too many failures on camera {self.camera_no}")
                        break
                    time.sleep(0.01)
                    continue

                if frame.shape[:2] != (360, 640):
                    frame = cv2.resize(frame, (640, 360))
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)

                with self.frame_lock:
                    self.latest_frame = frame.copy()
                    self.frame_count += 1

                self.last_frame_time = now
                consecutive_failures = 0

                # FPS log every 30s
                if now - self.last_fps_check >= 30:
                    fps = self.frame_count / (now - self.last_fps_check)
                    print(f"📸 Camera {self.camera_no} FPS: {fps:.2f} (target {self.target_fps})")
                    self.frame_count = 0
                    self.last_fps_check = now

            except Exception as e:
                print(f"⚠️ Frame error cam {self.camera_no}: {e}")
                time.sleep(0.01)

    def read(self):
        with self.frame_lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
            return False, None

    def stop(self):
        self.running = False
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
        print(f"🛑 Camera {self.camera_no} stopped")

class CameraConnection:
    MAX_CAMERAS = 2

    def __init__(self, width: int = 640, height: int = 360) -> None:
        self.size_width = width
        self.size_height = height
        self.cameras = {}
        self.backend2local = {}
        self.Amount_cameras = 0
        self.reset_camera = False
        self.cameras_connected = []
        self.ip_camera_threads = {}  # Track IP camera threads
        self.next_no = 1
        
        # CRITICAL: Frame timing control
        self.target_fps = 10  # Lower FPS for reduced latency
        self.frame_interval = 1.0 / self.target_fps
        self.last_read_time = 0

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

    def _get_free_cameraNO(self):
        """Find the smallest available cameraNO starting from 1"""
        if not self.cameras:
            return 1
        used = set(self.cameras.keys())
        n = 1
        while n in used:
            n += 1
        return n

    def _remove_camera(self, no: int, box_models=None, value_counter=None):
        """Low-level cleanup of one camera slot"""
        cam = self.cameras.pop(no, None)
        if not cam:
            logger.warning(f"Camera {no} not found, nothing to delete")
            return False

        try:
            if "ip_camera_obj" in cam:   # IP camera
                cam["ip_camera_obj"].stop()
                self.ip_camera_threads.pop(no, None)
                logger.info(f"Stopped IP camera {no}")

            elif "cam" in cam:          # USB / Pi / webcam
                if cam["cam"] is not None:
                    cam["cam"].release()
                    logger.info(f"Released webcam resource for camera {no}")
                if "index" in cam and cam["index"] is not None:
                    logger.info(f"Freed /dev/video{cam['index']} for reuse")

            else:                       # Dummy slot
                logger.info(f"Removed dummy slot {no}")

            # purge stale model & counters
            if box_models is not None:
                for idx, m in list(enumerate(box_models)):
                    if hasattr(m, "cameraNO") and m.cameraNO == no:
                        box_models.pop(idx)
                        logger.info(f"Removed box_model for camera {no}")

            if value_counter is not None and no in value_counter:
                value_counter.pop(no, None)
                logger.info(f"Removed value_counter entry for camera {no}")

        except Exception as e:
            logger.error(f"Error while removing camera {no}: {e}", exc_info=True)

        self.Amount_cameras -= 1

        polygon_store.mark_deleted(no)

        if self.Amount_cameras <= 0:
            self.reset_camera = True

        self.set_cameras_on_device()

        return True

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
            
            # CRITICAL: Set to 15 FPS instead of 20
            cap.set(cv2.CAP_PROP_FPS, 15)
            
        except Exception as e:
            logger.warning(f"Could not set camera properties: {e}")

    def apply_config(self, camera_setting: dict):
        try:
            self.set_cameras_on_device()
            detected = set(self.get_cameras_on_device() or [])
            used = set(c.get("index") for c in self.cameras.values() if "index" in c)
            # Parse backend camera list
            cams = (camera_setting or {}).get('cameras', [])
            if isinstance(cams, dict):
                cams = [cams]
            elif not isinstance(cams, list):
                cams = []

            # First: remove cameras not in backend
            self.sync_remaining_cameras(cams)

            # Update list of physically connected webcams
            self.set_cameras_on_device()
            detected = set(self.get_cameras_on_device() or [])
            used = set(c.get("index") for c in self.cameras.values() if "index" in c)

            # Add / update backend cameras
            for cam in cams:
                ctype = (cam.get('type') or '').lower()

                if ctype in ('webcam', 'usb', 'pi', 'pi_cam'):
                    idx = cam.get('index')
                    if idx is None or idx not in detected or idx in used:
                        candidate = next((d for d in detected if d not in used), None)
                        if candidate is None:
                            logger.warning("No free detected webcam index available; skipping %s", cam)
                            continue
                        idx = candidate
                    payload = {**cam, 'index': idx}
                    ok = self.add_webcam_pi_camera(payload)
                    if ok:
                        used.add(idx)

                elif ctype in ('ip', 'rtsp', 'http'):
                    self.add_ip_camera_optimized(cam)

                else:
                    logger.warning(f"Unknown camera type '{ctype}' for {cam}")

            if self.Amount_cameras == 0:
                logger.error("apply_config finished but no camera opened.")
        except Exception as e:
            logger.error(f"apply_config error: {e}", exc_info=True)

    def read_frame(self) -> list:
        frames = []
        connected = False

        for camNO in sorted(self.cameras.keys()):
            cam = self.cameras[camNO]
            try:
                if "ip_camera_obj" in cam:
                    ret, frame = cam["ip_camera_obj"].read()
                else:
                    ret, frame = cam["cam"].read()

                if not ret or frame is None or frame.size == 0:
                    logger.debug(f"No frame yet from camera {camNO}")  # ⬅ downgrade to debug
                    continue

                if frame.shape[:2] != (self.size_height, self.size_width):
                    frame = cv2.resize(frame, (self.size_width, self.size_height))
                if not frame.flags['C_CONTIGUOUS']:
                    frame = np.ascontiguousarray(frame)

                frames.append(frame)
                connected = True

            except Exception as e:
                logger.error(f"Error reading from camera {camNO}: {e}")

        if not connected:
            logger.warning("No connected camera (all feeds returned empty)")  # single message

        return frames

    def add_webcam_pi_camera(self, camera: dict) -> bool:
        if self.Amount_cameras > self.MAX_CAMERAS:
            logger.warning(f"Maximum camera limit reached ({self.Amount_cameras}/{self.MAX_CAMERAS}). Skipping add.")
            return False
        try:

            requested_no = camera.get("cameraNO")

            if requested_no is None:
                logger.warning("No cameraNO from backend, assigning fallback local NO")
                cameraNO = self._get_free_cameraNO()
            else:
                cameraNO = requested_no

            camera_index = camera.get("index")
            if camera_index is None:
                available = [i for i in self.cameras_connected
                            if all(c.get("index") != i for c in self.cameras.values())]
                if not available:
                    logger.warning(f"No free webcam index available for cameraNO {cameraNO}")
                    return False
                camera_index = available[0]

            # avoid duplicate index
            if any(c.get("index") == camera_index for c in self.cameras.values()):
                logger.warning(f"Index {camera_index} already in use")
                return False

            cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
            if not cap.isOpened():
                logger.warning(f"Cannot open webcam at index {camera_index}")
                return False

            self._set_common_props(cap)
            ret, test_frame = cap.read()
            if not ret or test_frame is None:
                logger.error(f"Camera {camera_index} opened but cannot read frames")
                cap.release()
                return False

            self.cameras[cameraNO] = {
                "cameraNO": cameraNO,
                "cam": cap,
                "name": camera["name"],
                "index": camera_index
            }
            self.Amount_cameras += 1
            logger.info(f"Webcam {cameraNO} added at index {camera_index}")

            polygon_store.adopt_or_init(cameraNO)

            self.backend2local[requested_no] = cameraNO
            return True

        except Exception as e:
            logger.error(f"Error adding webcam: {e}", exc_info=True)
            return False

    def add_ip_camera_optimized(self, camera: dict) -> bool:
        if self.Amount_cameras >= self.MAX_CAMERAS:
            logger.warning(f"Maximum camera limit reached ({self.Amount_cameras}/{self.MAX_CAMERAS}). Skipping add.")
            return False
        try:
            requested_no = camera.get("cameraNO")

            if requested_no is None:
                logger.warning("No cameraNO from backend, assigning fallback local NO")
                cameraNO = self._get_free_cameraNO()
            else:
                cameraNO = requested_no

            rtsp_url = camera["ip"]
            name = camera["name"]

            ip_cam = LowLatencyIPCamera(rtsp_url, cameraNO, name, target_fps=15)

            if not ip_cam.start():
                logger.error(f"Failed to start 15 FPS IP camera {cameraNO}")
                return False

            self.cameras[cameraNO] = {
                "cameraNO": cameraNO,
                "name": name,
                "ip": rtsp_url,
                "ip_camera_obj": ip_cam
            }
            self.ip_camera_threads[cameraNO] = ip_cam
            self.Amount_cameras += 1
            logger.info(f"15 FPS IP camera {cameraNO} added successfully")

            polygon_store.adopt_or_init(cameraNO)

            self.backend2local[requested_no] = cameraNO
            return True

        except Exception as e:
            logger.error(f"Error adding 15 FPS IP camera: {e}", exc_info=True)
            return False

    def add_ip_camera(self, camera: dict):
        """Fallback method - use optimized version instead"""
        logger.info("Using optimized IP camera method")
        self.add_ip_camera_optimized(camera)

    def del_camera(self, target, box_models=None, value_counter=None):
        """Delete one or more cameras and free resources cleanly."""
        if isinstance(target, int):
            nos = [target]
        elif isinstance(target, dict) and "cameraNO" in target:
            nos = [target["cameraNO"]]
        elif isinstance(target, list):
            if target and isinstance(target[0], dict):
                nos = [t.get("cameraNO") for t in target if "cameraNO" in t]
            else:
                nos = [int(t) for t in target]
        else:
            logger.warning("del_camera: unsupported target type")
            return

        for no in nos:
            self._remove_camera(no, box_models, value_counter)

    def del_all_camera(self):
        for cam in list(self.cameras.values()):
            if "ip_camera_obj" in cam:
                cam["ip_camera_obj"].stop()
            else:
                cam["cam"].release()

        self.ip_camera_threads.clear()
        self.cameras.clear()
        self.Amount_cameras = 0
        self.reset_camera = True

    def get_cameras_on_device(self):
        return self.cameras_connected

    def sync_remaining_cameras(self, remaining: list[dict], box_models=None, value_counter=None):
        """Keep only cameras in `remaining`. Remove others with full cleanup."""
        remain_local = set()
        for cam in (remaining or []):
            bno = cam.get("cameraNO")
            lno = self.backend2local.get(bno, bno)
            remain_local.add(lno)

        current_cams = list(self.cameras.keys())
        to_remove = [no for no in current_cams if no not in remain_local]

        for no in to_remove:
            self._remove_camera(no, box_models, value_counter)

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