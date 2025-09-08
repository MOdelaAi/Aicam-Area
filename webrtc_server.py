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
# ----------------------------------------------------

current_stream = {
    "selected_cam": 0,
    "cameras": [
        {
            "id": 0,
            "polygons": [
                {"coord": [], "seen": 0, "name": ""},
                {"coord": [], "seen": 0, "name": ""}
            ]
        },
        {
            "id": 1,
            "polygons": [
                {"coord": [], "seen": 0, "name": ""},
                {"coord": [], "seen": 0, "name": ""}
            ]
        }
    ]
}

POLYGON_FILE = Path("polygons.json")

if POLYGON_FILE.exists():
    try:
        with POLYGON_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # sanity check: must have "cameras" and "selected_cam"
        if "cameras" in data and isinstance(data["cameras"], list):
            current_stream = data
            print(f"📂 Loaded polygons.json with {len(current_stream['cameras'])} cameras")
        else:
            print("⚠️ polygons.json invalid format, using default")
    except Exception as e:
        print("⚠️ Failed to load polygons.json, using default:", e)

pcs = set()

class FrameTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        frame = FrameSource.latest_frame
        if frame is None:
            print("⚠️ FrameSource.latest_frame is None")
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        else:
            pass
            # print("✅ Got frame with shape:", frame.shape)

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
        await asyncio.sleep(30)
        for pc in list(pcs):
            if pc.connectionState in ("closed", "failed", "disconnected"):
                await pc.close()
                pcs.discard(pc)

async def cleanup():
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

async def set_frame(request):
    """Switch active camera feed (0-based index). Accepts JSON or query param."""
    try:
        cam_raw = None

        # Try JSON body first
        if request.can_read_body:
            try:
                data = await request.json()
                cam_raw = data.get("cam", None)
            except Exception:
                cam_raw = None

        # Fallback to query string ?cam=1
        if cam_raw is None:
            cam_raw = request.query.get("cam", None)

        if cam_raw is None:
            return web.json_response({"ok": False, "error": "missing 'cam' parameter"}, status=400)

        # Ensure integer
        try:
            cam = int(cam_raw)
        except Exception:
            return web.json_response({"ok": False, "error": "'cam' must be an integer"}, status=400)

        n_cams = len(current_stream["cameras"])
        if cam < 0 or cam >= n_cams:
            return web.json_response(
                {"ok": False, "error": f"cam out of range (0..{n_cams-1})"},
                status=400
            )

        # Update selection
        with state_lock:
            current_stream["selected_cam"] = cam
            # OPTIONAL: persist selection so it survives restart
            try:
                with POLYGON_FILE.open("w", encoding="utf-8") as f:
                    json.dump(current_stream, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print("⚠️ Failed to persist selected_cam:", e)

        return web.json_response({"ok": True, "selected_cam": cam})

    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def get_polygons(request):
    try:
        if POLYGON_FILE.exists():
            with POLYGON_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response(data)
        else:
            return web.json_response(current_stream)  # fallback to memory
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def clear_polygons(request):
    try:
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except:
                data = {}

        cam_id = data.get("camera_id", None)

        with state_lock:
            if cam_id is None:
                # clear ALL cameras
                for cam in current_stream["cameras"]:
                    cam["polygons"] = [
                        {"coord": [], "seen": 0, "name": ""},
                        {"coord": [], "seen": 0, "name": ""}
                    ]
                cleared = "all"
            else:
                cam_id = int(cam_id)
                if cam_id < 0 or cam_id >= len(current_stream["cameras"]):
                    return web.json_response({"ok": False, "error": "invalid camera id"}, status=400)
                current_stream["cameras"][cam_id]["polygons"] = [
                    {"coord": [], "seen": 0, "name": ""},
                    {"coord": [], "seen": 0, "name": ""}
                ]
                cleared = cam_id

        # 🔑 overwrite polygons.json here
        try:
            with POLYGON_FILE.open("w", encoding="utf-8") as f:
                json.dump(current_stream, f, ensure_ascii=False, indent=2)
            print(f"🗑️ polygons.json updated after clearing {cleared}")
        except Exception as e:
            print("⚠️ Failed to write polygons.json:", e)

        return web.json_response({"ok": True, "cleared": cleared})

    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def save_polygons(request):
    try:
        data = await request.json()
        cam_id = int(data.get("camera_id", 0))
        polygons = data.get("polygons", [])

        if cam_id < 0 or cam_id >= len(current_stream["cameras"]):
            return web.json_response({"ok": False, "error": "invalid camera id"}, status=400)

        with state_lock:
            cam = current_stream["cameras"][cam_id]
            # overwrite with received polygons (max 2)
            cam["polygons"] = [
                {"coord": p.get("coord", []), "seen": p.get("seen", 0), "name": p.get("name", "")}
                for p in polygons[:2]
            ]
            # if less than 2 polygons, pad with empty
            while len(cam["polygons"]) < 2:
                cam["polygons"].append({"coord": [], "seen": 0, "name": ""})

        # persist whole structure into local json
        try:
            with POLYGON_FILE.open("w", encoding="utf-8") as f:
                json.dump(current_stream, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("⚠️ Failed to save polygons to file:", e)

        return web.json_response({"ok": True, "saved": len(polygons), "camera_id": cam_id})
    except Exception as e:
        traceback.print_exc()
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

        # สร้าง PeerConnection ใหม่
        pc = RTCPeerConnection()
        pcs.add(pc)

        pc_id = str(uuid.uuid4())[:8]
        print(f"🎥 New peer connection: {pc_id}")

        # เพิ่ม callback
        @pc.on("connectionstatechange")
        async def on_state_change():
            print(f"🔄 [{pc_id}] Connection state:", pc.connectionState)
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await pc.close()
                pcs.discard(pc)
                print(f"❌ [{pc_id}] Connection closed and removed")

        # เพิ่ม video track
        pc.addTrack(FrameTrack())

        # ทำขั้นตอน handshake
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

    print(current_stream)

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
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
        allow_methods=["POST", "GET", "OPTIONS"]
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


