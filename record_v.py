# record_v.py

import cv2
import time
import os
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from logger_config import setup_logger

logger = setup_logger(__name__)

""" 
Frame structure:
all_frames = [
    (cam1_frame),
    (cam2_frame)
]
"""

class MultiCameraRecorder:
    def __init__(
        self,
        cams,
        video_dir: str = "/home/user/video",
        fourcc: str = "mp4v",
        file_duration: int = 60,         
        frame_size: Tuple[int, int] = (0, 0),  # (0,0) => autosize from first frame
        fps: int = 5,                    
        max_storage_bytes: int = 10 * 1024 * 1024 * 1024,  # 10 GB
        idle_close_seconds: int = 10,    # close writer if no frames for N seconds
    ):
        self.video_dir = video_dir
        os.makedirs(self.video_dir, exist_ok=True)

        self.file_duration = file_duration
        self._configured_frame_size = frame_size
        self.fps = fps
        self.MAX_STORAGE_BYTES = max_storage_bytes
        self.idle_close_seconds = idle_close_seconds

        self.fourcc = cv2.VideoWriter_fourcc(*fourcc)
        self.cameras = cams

        # writers & state per cam
        self.out_writers: Dict[int, Optional[cv2.VideoWriter]] = {}
        self.start_times: Dict[int, float] = {}
        self.last_write_times: Dict[int, float] = {}
        self.last_frame_ts: Dict[int, float] = {}
        self.frame_size_by_cam: Dict[int, Tuple[int, int]] = {}

        # Frame timing control for proper duration
        self.frame_interval = 1.0 / self.fps  # Exact time between frames

    # ---------- path helpers ----------

    def _cam_root(self, cam_index: int) -> str:
        cam_id = cam_index + 1
        root = os.path.join(self.video_dir, f"cam_{cam_id}")
        os.makedirs(root, exist_ok=True)
        return root

    def _current_ts(self) -> str:
        return datetime.now().strftime("%-d_%b_%Y_%H%M%S")

    def _file_path(self, cam_index: int) -> str:
        cam_id = cam_index + 1
        folder = self._cam_root(cam_index)
        fname = f"cam_{cam_id}_{self._current_ts()}.mp4"
        return os.path.join(folder, fname)

    # ---------- storage management ----------

    def _list_all_videos(self) -> list:
        videos = []
        try:
            for d in os.listdir(self.video_dir):
                if not d.startswith("cam_"):
                    continue
                cam_dir = os.path.join(self.video_dir, d)
                if not os.path.isdir(cam_dir):
                    continue
                for f in os.listdir(cam_dir):
                    if f.endswith(".mp4"):
                        videos.append(os.path.join(cam_dir, f))
        except FileNotFoundError:
            pass
        return videos

    def _total_size(self) -> int:
        total = 0
        for fpath in self._list_all_videos():
            try:
                total += os.path.getsize(fpath)
            except Exception:
                pass
        return total

    def _delete_oldest_file(self):
        files = self._list_all_videos()
        if not files:
            return
        oldest = min(files, key=os.path.getctime)
        try:
            os.remove(oldest)
            logger.info(f"[Recorder] Deleted oldest file: {oldest}")
        except Exception as e:
            logger.error(f"[Recorder] Failed to delete {oldest}: {e}", exc_info=True)

    # ---------- writer lifecycle ----------

    def _ensure_cam_ready(self, cam_index: int, sample_frame: Optional[Any]):
        # Create camera directory
        _ = self._cam_root(cam_index)

        # Set frame size if not already set
        if cam_index not in self.frame_size_by_cam:
            if self._configured_frame_size in [(0, 0), None] and sample_frame is not None:
                h, w = sample_frame.shape[:2]
                self.frame_size_by_cam[cam_index] = (w, h)
            else:
                self.frame_size_by_cam[cam_index] = (
                    self._configured_frame_size if self._configured_frame_size not in [(0, 0), None]
                    else (640, 480)
                )

        self._open_writer(cam_index)

    def _open_writer(self, cam_index: int):
        sz = self.frame_size_by_cam.get(cam_index, (640, 480))
        path = self._file_path(cam_index)
        
        self.out_writers[cam_index] = cv2.VideoWriter(path, self.fourcc, self.fps, sz)
        self.start_times[cam_index] = time.time()
        self.last_write_times[cam_index] = time.time()
        
        logger.info(f"[Recorder][cam{cam_index+1}] Opened {path} @ {self.fps} fps")

    def _rotate(self, cam_index: int):
        writer = self.out_writers.get(cam_index)
        if writer is not None:
            writer.release()
        self._open_writer(cam_index)

    def _close_writer(self, cam_index: int):
        writer = self.out_writers.get(cam_index)
        if writer is not None:
            try: 
                writer.release()
                logger.info(f"[Recorder][cam{cam_index+1}] Writer closed due to inactivity")
            except Exception: 
                pass
            self.out_writers[cam_index] = None

    # ---------- frame helpers ----------

    def _resize_if_needed(self, cam_index: int, frame):
        if frame is None:
            return None
        target = self.frame_size_by_cam.get(cam_index)
        if not target:
            return frame
        h, w = frame.shape[:2]
        if (w, h) != target:
            try:
                return cv2.resize(frame, target)
            except Exception:
                return frame
        return frame

    # ---------- public API ----------

    def record_video(self, frames: List[Optional[Any]]):
        """
        Record video frames from multiple cameras
        
        Args:
            frames: List of frames, one per camera [cam1_frame, cam2_frame, ...]
                   Each frame can be None if no frame available from that camera
        """
        try:
            # Global storage cap - delete oldest files when storage limit is reached
            while self._total_size() > self.MAX_STORAGE_BYTES:
                self._delete_oldest_file()

            now = time.time()

            for cam_index, frame in enumerate(frames):
                has_frame = frame is not None

                if has_frame:
                    self.last_frame_ts[cam_index] = now

                # Initialize camera if we have a frame and it's not set up yet
                if cam_index not in self.frame_size_by_cam and has_frame:
                    self._ensure_cam_ready(cam_index, frame)

                # If writer hasn't been opened yet, skip this camera
                if cam_index not in self.out_writers:
                    continue

                # Idle timeout → close writer
                last_ts = self.last_frame_ts.get(cam_index, 0)
                if last_ts and (now - last_ts > self.idle_close_seconds):
                    self._close_writer(cam_index)

                # Frame available but writer is closed → reopen
                if has_frame and self.out_writers.get(cam_index) is None:
                    self._ensure_cam_ready(cam_index, frame)

                # Rotate files after duration (default 1 minute)
                if (self.out_writers.get(cam_index) is not None and 
                    now - self.start_times.get(cam_index, now) >= self.file_duration):
                    self._rotate(cam_index)

                # Write frame if available and writer is open
                if has_frame and self.out_writers.get(cam_index) is not None:
                    resized_frame = self._resize_if_needed(cam_index, frame)
                    self.out_writers[cam_index].write(resized_frame)

        except Exception as e:
            logger.error(f"[Recorder] Error writing video: {e}", exc_info=True)

    def close(self):
        """Close all video writers"""
        for cam_index, writer in list(self.out_writers.items()):
            if writer is not None:
                try: 
                    writer.release()
                    logger.info(f"[Recorder][cam{cam_index+1}] Writer closed")
                except Exception: 
                    pass
        self.out_writers.clear()

    def get_status(self) -> Dict[str, Any]:
        """Get current recording status"""
        status = {
            'active_cameras': [],
            'total_storage_bytes': self._total_size(),
            'max_storage_bytes': self.MAX_STORAGE_BYTES,
            'storage_usage_percent': (self._total_size() / self.MAX_STORAGE_BYTES) * 100
        }
        
        for cam_index, writer in self.out_writers.items():
            if writer is not None:
                status['active_cameras'].append(f"cam_{cam_index + 1}")
        
        return status