import cv2
import os
import time
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from logger_config import setup_logger

logger = setup_logger(__name__)

class MultiCameraRecorder:
    def __init__(
        self,
        cams,
        video_dir: str = "/home/user/video",
        fourcc: str = "mp4v",
        frame_size: Tuple[int, int] = (0, 0),
        fps: int = 16,
        max_frames: int = 1000,   # rotate after N frames
        max_storage_bytes: int = 10 * 1024 * 1024 * 1024,
    ):
        self.video_dir = video_dir
        os.makedirs(self.video_dir, exist_ok=True)

        self._configured_frame_size = frame_size
        self.fps = fps
        self.max_frames = max_frames
        self.MAX_STORAGE_BYTES = max_storage_bytes


        self.fourcc = cv2.VideoWriter_fourcc(*fourcc)
        self.cameras = cams

        # Writers & state per cam
        self.out_writers: Dict[int, Optional[cv2.VideoWriter]] = {}
        self.frame_size_by_cam: Dict[int, Tuple[int, int]] = {}
        self.frame_counts: Dict[int, int] = {}  # frames written per file
        self.start_times: Dict[int, float] = {}

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
        return sum(os.path.getsize(f) for f in self._list_all_videos() if os.path.exists(f))

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
        if cam_index not in self.frame_size_by_cam:
            if self._configured_frame_size in [(0, 0), None] and sample_frame is not None:
                h, w = sample_frame.shape[:2]
                self.frame_size_by_cam[cam_index] = (w, h)
            else:
                self.frame_size_by_cam[cam_index] = (
                    self._configured_frame_size
                    if self._configured_frame_size not in [(0, 0), None]
                    else (640, 360)
                )

        if cam_index not in self.out_writers or self.out_writers[cam_index] is None:
            self._open_writer(cam_index)

    def _open_writer(self, cam_index: int):
        sz = self.frame_size_by_cam.get(cam_index, (640, 360))
        path = self._file_path(cam_index)

        self.out_writers[cam_index] = cv2.VideoWriter(path, self.fourcc, float(self.fps), sz)
        self.frame_counts[cam_index] = 0
        self.start_times[cam_index] = time.time()   # <--- added
        logger.info(f"[Recorder][cam{cam_index+1}] Opened {path} @ {self.fps} fps, size={sz}")

    def _rotate(self, cam_index: int):
        """Close current file and open new one after frame limit reached."""
        writer = self.out_writers.get(cam_index)
        if writer is not None:
            writer.release()
        self._open_writer(cam_index)

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
    def record_video(self, frames: List[Optional[Any]], actual_fps: int = 8):
        """Write frames directly to video files with frame-based or time-based rotation."""
        try:
            # Clean up storage if needed
            while self._total_size() > self.MAX_STORAGE_BYTES:
                self._delete_oldest_file()

            duplication_factor = 3
            current_time = time.time()

            for cam_index, frame in enumerate(frames):
                if frame is None:
                    continue

                # Ensure camera writer is ready
                self._ensure_cam_ready(cam_index, frame)
                writer = self.out_writers.get(cam_index)
                if writer is None:
                    continue

                # --- Rotate if max_frames reached OR 60 seconds passed ---
                if (
                    self.frame_counts.get(cam_index, 0) >= self.max_frames
                    or (current_time - self.start_times.get(cam_index, current_time)) >= 160
                ):
                    self._rotate(cam_index)

                # Resize frame
                resized_frame = self._resize_if_needed(cam_index, frame)
                if resized_frame is None:
                    continue

                # Duplicate frames to simulate smoother FPS
                for _ in range(duplication_factor):
                    writer.write(resized_frame)
                    self.frame_counts[cam_index] += 1

        except Exception as e:
            logger.error(f"[Recorder] Error writing video: {e}", exc_info=True)

    def close(self):
        """Close all video writers."""
        for cam_index, writer in list(self.out_writers.items()):
            if writer is not None:
                try:
                    writer.release()
                    logger.info(f"[Recorder][cam{cam_index+1}] Writer closed")
                except Exception:
                    pass
        self.out_writers.clear()

    def get_status(self) -> Dict[str, Any]:
        """Get current recording status."""
        return {
            'active_cameras': [f"cam_{i+1}" for i, w in self.out_writers.items() if w is not None],
            'total_storage_bytes': self._total_size(),
            'max_storage_bytes': self.MAX_STORAGE_BYTES,
            'storage_usage_percent': (self._total_size() / self.MAX_STORAGE_BYTES) * 100,
            'target_fps': self.fps,
            'max_frames': self.max_frames,
        }
