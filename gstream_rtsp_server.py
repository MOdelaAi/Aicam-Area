
import threading
import numpy as np
import time
import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GObject

Gst.init(None)

class FastFrameSource:
    """Simplified frame source optimized for speed"""
    latest_frame = None
    lock = threading.Lock()
    
    @classmethod
    def update_frame(cls, frame: np.ndarray) -> bool:
        if frame is None or frame.size == 0:
            return False
        
        with cls.lock:
            cls.latest_frame = frame
            return True
    
    @classmethod
    def get_frame(cls) -> np.ndarray:
        with cls.lock:
            return cls.latest_frame

# Use this as your FrameSource
FrameSource = FastFrameSource

class BestRTSPFactory(GstRtspServer.RTSPMediaFactory):
    """Best balance of speed and reliability for your Pi setup"""
    
    def __init__(self, fps: int = 20, quality: int = 60):
        super().__init__()
        self.fps = fps
        self.quality = quality
        self.duration = Gst.util_uint64_scale_int(1, Gst.SECOND, self.fps)
        self.frame_count = 0
        self.caps_set = False
        
    def do_create_element(self, url):
        """Optimized MJPEG pipeline - matches your HTTP performance"""
        pipeline_str = (
            f"appsrc name=source is-live=true format=time block=false "
            f"max-bytes=1048576 min-latency=0 max-latency=0 "
            f"! videoconvert n-threads=2 "
            f"! jpegenc quality={self.quality} idct-method=ifast "
            f"! rtpjpegpay name=pay0 pt=26 mtu=1200"
        )
        return Gst.parse_launch(pipeline_str)
    
    def on_need_data(self, appsrc, length):
        """Fast frame pushing with minimal overhead"""
        frame = FrameSource.get_frame()
        if frame is None:
            return
        
        # Set caps once
        if not self.caps_set:
            h, w, c = frame.shape
            caps_str = f"video/x-raw,format=BGR,width={w},height={h},framerate={self.fps}/1"
            caps = Gst.Caps.from_string(caps_str)
            appsrc.set_caps(caps)
            self.caps_set = True
        
        # Create and push buffer
        frame_bytes = frame.tobytes()
        buf = Gst.Buffer.new_wrapped(frame_bytes)
        buf.pts = self.frame_count * self.duration
        buf.dts = buf.pts
        
        appsrc.emit('push-buffer', buf)
        self.frame_count += 1
    
    def do_configure(self, rtsp_media):
        """Minimal configuration for maximum speed"""
        pipeline = rtsp_media.get_element()
        appsrc = pipeline.get_child_by_name('source')
        
        if appsrc:
            appsrc.set_property('is-live', True)
            appsrc.set_property('block', False)
            appsrc.connect('need-data', self.on_need_data)
        
        rtsp_media.set_latency(0)
        rtsp_media.set_suspend_mode(GstRtspServer.RTSPSuspendMode.NONE)

def start_rtsp_server(port=8554, fps=20, quality=30, mount="/stream"):
    """Start the fastest RTSP server for your use case"""
    server = GstRtspServer.RTSPServer()
    server.set_service(str(port))
    
    factory = BestRTSPFactory(fps=fps, quality=quality)
    factory.set_shared(True)
    
    mount_points = server.get_mount_points()
    mount_points.add_factory(mount, factory)
    
    server_id = server.attach(None)
    if server_id == 0:
        print("[RTSP] Failed to start server")
        return False
    
    print(f"Fast RTSP Server: rtsp://<host>:{port}{mount}")
    print(f"Mode: MJPEG, FPS: {fps}, Quality: {quality}")
    
    return True