# webrtc_server.py

import asyncio
import threading
from aiohttp import web
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from gstream_rtsp_server import FrameSource
import cv2
import av
import numpy as np
import traceback
import uuid
from collections import defaultdict
import json
import time
import base64
from polygon_store import PolygonStore
from pathlib import Path
import sys, os

state_lock = threading.Lock()

def _bundle_base() -> Path:
    """
    Return the directory holding bundled data:
      - onefile: sys._MEIPASS
      - onedir:  <app_dir>/_internal
      - dev:     directory of this file
    """
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)                                  # onefile
        return Path(sys.executable).resolve().parent / "_internal"     # onedir
    return Path(__file__).resolve().parent                              # dev

def _static_dir() -> Path:
    candidates = [
        _bundle_base() / "static",                         # bundled static
        Path(sys.executable).resolve().parent / "static",  # fallback onedir root
        Path(__file__).resolve().parent / "static",        # dev source tree
        Path.cwd() / "static",                             # cwd fallback
    ]
    for p in candidates:
        if p.exists():
            print(f"[webrtc] Serving static from: {p}")
            return p
    raise FileNotFoundError("static not found; tried:\n" + "\n".join(map(str, candidates)))

# ----------------------------------------------------------------------
store = PolygonStore(Path("polygons.json"), max_polygons_per_cam=2)

data = store.get_all()
_current_sel_id = data.get("selected_cam_id")
if _current_sel_id is None and data.get("cameras"):
    # default to the first camera's id if none selected yet
    _current_sel_id = data["cameras"][0].get("id")
    store.set_selected_cam_id(_current_sel_id)

current_stream = {
    "selected_cam_id": _current_sel_id,
    "cameras": data.get("cameras", [])
}
# -----------------------------------------------------------------------

pcs = set()

class FrameTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        frame, timestamp = FrameSource.get_frame()
        if frame is None or time.time() - timestamp > 0.5:  # ดรอปเฟรมเก่ากว่า 0.5 วินาที
            print("⚠️ Dropping stale frame")
            return await asyncio.sleep(0.01)  # รอเฟรมใหม่

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            av_frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            av_frame.pts = pts
            av_frame.time_base = time_base
            return av_frame
        except Exception as e:
            print("❌ Frame conversion error:", e)
            traceback.print_exc()
            await asyncio.sleep(0.05)  # wait before retry
            return await self.recv()

async def cleanup_stale_peers():
    while True:
        await asyncio.sleep(10)  # Check every 10 seconds instead of 30
        for pc in list(pcs):
            if pc.connectionState in ("closed", "failed", "disconnected"):
                await pc.close()
                pcs.discard(pc)

async def cleanup():
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

async def set_frame(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    try:
        cam_id = int(data.get("camera_id"))
    except Exception:
        return web.json_response({"ok": False, "error": "'camera_id' must be an integer"}, status=400)

    data_all = store.get_all()
    cameras = data_all.get("cameras", [])
    camera_ids = [c.get("id") for c in cameras]
    if cam_id not in camera_ids:
        return web.json_response({"ok": False, "error": f"camera_id {cam_id} not found"}, status=400)

    # Persist by ID
    store.set_selected_cam_id(cam_id)

    with state_lock:
        current_stream["selected_cam_id"] = cam_id
        current_stream["cameras"] = cameras  # keep local snapshot aligned

    print(f"[webrtc] set_frame → camera_id={cam_id}")
    return web.json_response({"ok": True, "camera_id": cam_id})


async def get_polygons(request):
    try:
        data = store.get_all()
        cameras = data.get("cameras", [])
        sel_id = data.get("selected_cam_id", None)

        return web.json_response({
            "cameras": cameras,
            "selected_cam_id": sel_id
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def clear_polygons(request):
    try:
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except:
                pass
        cam_id = data.get("camera_id", None)
        if cam_id is None:
            store.clear_polygons(None)
            cleared = "all"
        else:
            store.clear_polygons(int(cam_id))
            cleared = int(cam_id)
        return web.json_response({"ok": True, "cleared": cleared})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def save_polygons(request):
    try:
        data = await request.json()
        cam_id = int(data.get("camera_id"))
        polygons = data.get("polygons", [])

        cameras = store.get_all()["cameras"]
        if cam_id not in [c.get("id") for c in cameras]:
            return web.json_response({"ok": False, "error": f"camera_id {cam_id} not found"}, status=400)

        store.set_polygons(cam_id, polygons)
        return web.json_response({"ok": True, "saved": len(polygons), "camera_id": cam_id})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def get_captured_image_jpg(request):
    frame = FrameSource.latest_raw_frame
    if frame is None:
        return web.Response(status=503, text="No frame available yet")

    # optional resize
    w = request.query.get("w")
    h = request.query.get("h")
    if w and h:
        try:
            w, h = int(w), int(h)
            if w > 0 and h > 0:
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
        except Exception:
            pass

    # format
    fmt = request.query.get("fmt", "jpg").lower()
    if fmt not in ("jpg", "jpeg", "png"):
        fmt = "jpg"

    encode_params = []
    if fmt in ("jpg", "jpeg"):
        q = request.query.get("q")
        try:
            q = int(q) if q is not None else 85
        except Exception:
            q = 85
        q = max(70, min(95, q))
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), q]

    ok, buf = cv2.imencode(f".{fmt}", frame, encode_params)
    if not ok:
        return web.Response(status=500, text="Failed to encode image")

    content_type = "image/jpeg" if fmt in ("jpg", "jpeg") else "image/png"
    return web.Response(
        body=bytes(buf),
        content_type=content_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

async def offer(request):
    try:
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        # Create a new PeerConnection
        pc = RTCPeerConnection()
        pcs.add(pc)

        pc_id = str(uuid.uuid4())[:8]
        print(f"🎥 New peer connection: {pc_id}")

        # Add callbacks
        @pc.on("connectionstatechange")
        async def on_state_change():
            print(f"🔄 [{pc_id}] Connection state:", pc.connectionState)
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                pcs.discard(pc)
                print(f"❌ [{pc_id}] Connection closed and removed")

        # Add video track
        pc.addTrack(FrameTrack())

        # Perform the handshake
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.json_response({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })

    except Exception as e:
        print("❌ Error in /offer:", e)
        traceback.print_exc()
        return web.json_response({
            "error": str(e),
            "trace": traceback.format_exc()
        }, status=500)

async def redirect_video_feed(request):
    raise web.HTTPFound(location="/") 

def start_webrtc_server():
    app = web.Application()
    
    # WebRTC signaling
    app.router.add_post("/offer", offer)
    app.router.add_post("/set_frame", set_frame)
    app.router.add_post("/save_polygons", save_polygons)
    app.router.add_post("/clear_polygons", clear_polygons)

    # print(current_stream)

    #redirect_video_feed
    app.router.add_get("/video_feed", redirect_video_feed)
    app.router.add_get("/capture.jpg", get_captured_image_jpg)   # binary image
    app.router.add_get("/polygons.json", get_polygons)


    static_dir = _static_dir()
    index_path = static_dir / "index.html"

    async def index(request):
        return web.FileResponse(path=str(index_path.resolve()))

    app.router.add_get("/", index)
    app.router.add_static("/static", path=str(static_dir.resolve()), name="static")

    # Enable CORS
    cors = aiohttp_cors.setup(app, defaults={
        "/offer": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["POST", "OPTIONS"]
        ),
        "/set_frame": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods=["POST", "OPTIONS"]
        )
    })

    for route in list(app.router.routes()):
        cors.add(route)

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        loop.create_task(cleanup_stale_peers())
        site = web.TCPSite(runner, "0.0.0.0", 5000)
        loop.run_until_complete(site.start())
        print("✅ WebRTC server running at http://<pi-ip>:5000")
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()


