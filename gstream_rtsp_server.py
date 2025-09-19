#gstream_rtsp_server.py

import cv2
import numpy as np
import time
import threading
import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GObject

Gst.init(None)

class RealtimeFrameSource:
    """Frame source that mimics ffplay's real-time behavior"""
    latest_frame = None
    lock = threading.RLock()
    frame_timestamp = 0
    
    @classmethod
    def update_frame(cls, frame: np.ndarray) -> bool:
        if frame is None or frame.size == 0:
            return False
        
        with cls.lock:
            # Always take the latest frame, drop old ones
            cls.latest_frame = frame.copy()
            cls.frame_timestamp = time.time()
            return True
    
    @classmethod
    def get_frame(cls):
        with cls.lock:
            return cls.latest_frame, cls.frame_timestamp

FrameSource = RealtimeFrameSource

class RealtimeRTSPFactory(GstRtspServer.RTSPMediaFactory):
    """RTSP factory that replicates ffplay's low-delay behavior"""
    
    def __init__(self, fps: int = 20, quality: int = 30):
        super().__init__()
        self.fps = fps
        self.quality = quality
        self.frame_count = 0
        self.caps_set = False
        
    def do_create_element(self, url):
        """Pipeline equivalent to ffplay's low_delay + nobuffer flags"""
        pipeline_str = (
            "appsrc name=source is-live=true format=time "
            "min-latency=0 max-latency=0 block=false max-bytes=65536 "
            "! queue max-size-buffers=1 max-size-time=0 leaky=downstream "
            "! videoconvert "
            "! jpegenc quality=30 idct-method=ifast "
            "! rtpjpegpay name=pay0 pt=26 mtu=1200 config-interval=0"
        )

        return Gst.parse_launch(pipeline_str)
    
    def on_need_data(self, appsrc, length):
        """Push frames immediately, no timing delays"""
        frame_data = FrameSource.get_frame()
        if frame_data[0] is None:
            return
        
        frame, timestamp = frame_data
        
        # Set caps once
        if not self.caps_set:
            h, w, c = frame.shape
            caps_str = f"video/x-raw,format=BGR,width={w},height={h},framerate={self.fps}/1"
            caps = Gst.Caps.from_string(caps_str)
            appsrc.set_caps(caps)
            self.caps_set = True
        
        # Create buffer with current timestamp (like setpts=0)
        frame_bytes = frame.tobytes()
        buf = Gst.Buffer.new_wrapped(frame_bytes)
        
        # Use actual system time, no artificial timing
        buf.pts = Gst.util_uint64_scale_int(int(timestamp * 1000000000), 1, 1000000000)
        buf.dts = buf.pts
        buf.duration = Gst.CLOCK_TIME_NONE  # No duration constraint
        
        appsrc.emit('push-buffer', buf)
        self.frame_count += 1
    
    def do_configure(self, rtsp_media):
        """Configure for absolute minimum latency"""
        pipeline = rtsp_media.get_element()
        appsrc = pipeline.get_child_by_name('source')
        
        if appsrc:
            appsrc.set_property('is-live', True)
            appsrc.set_property('block', False)
            appsrc.set_property('min-latency', 0)
            appsrc.set_property('max-latency', 0)
            appsrc.connect('need-data', self.on_need_data)
        
        # Media settings for real-time
        rtsp_media.set_latency(0)
        rtsp_media.set_suspend_mode(GstRtspServer.RTSPSuspendMode.NONE)

def create_realtime_camera_capture(camera_url):
    """Create OpenCV capture with ffplay-equivalent settings"""
    
    # For RTSP cameras, use equivalent of ffplay flags
    cap = cv2.VideoCapture(camera_url, cv2.CAP_FFMPEG)
    
    # Equivalent of -fflags nobuffer
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    
    # Equivalent of -flags low_delay  
    cap.set(cv2.CAP_PROP_FPS, 25)  # Match your camera's fps
    
    # Additional optimizations
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)   # Set explicit resolution
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    return cap

def optimize_camera_url(base_url):
    """Add parameters equivalent to ffplay flags"""
    # Your camera URL with low-latency parameters
    # Equivalent to -rtsp_transport tcp -max_delay 0
    if '?' in base_url:
        return f"{base_url}&tcp_mode=1&buffer_size=1&max_delay=0"
    else:
        return f"{base_url}?tcp_mode=1&buffer_size=1&max_delay=0"

def start_realtime_rtsp_server(port=8554, fps=20, quality=30, mount="/stream"):
    """Start RTSP server optimized for real-time like ffplay"""
    server = GstRtspServer.RTSPServer()
    server.set_service(str(port))
    
    factory = RealtimeRTSPFactory(fps=fps, quality=quality)
    factory.set_shared(True)
    
    mount_points = server.get_mount_points()
    mount_points.add_factory(mount, factory)
    
    server_id = server.attach(None)
    if server_id == 0:
        print("[RTSP] Failed to start server")
        return False
    
    print(f"[RTSP] Real-time server: rtsp://<host>:{port}{mount}")
    print("Client should use: ffplay -fflags nobuffer -flags low_delay rtsp://...")
    return True
