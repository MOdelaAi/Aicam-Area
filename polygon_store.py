from __future__ import annotations
from pathlib import Path
import json
import threading
from typing import List, Dict, Any, Optional
import os

class PolygonStore:
    def __init__(self, path: Path | str = "polygons.json", max_polygons_per_cam: int = 2):
        self.path = Path(path)
        self.max_polygons = max_polygons_per_cam
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            "selected_cam_id": None,
            "cameras": [],
            "deleted_ids": []
        }
        self._last_mtime = 0
        self._load()

    # --------------- internal helpers ---------------
    def _maybe_reload(self):
        """Reload polygons.json if the file has changed."""
        try:
            mtime = os.stat(self.path).st_mtime
            if mtime != self._last_mtime:
                self._load()
                self._last_mtime = mtime
        except FileNotFoundError:
            pass

    def _load(self):
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                # normalize
                if not isinstance(data.get("cameras"), list):
                    data["cameras"] = []
                if "deleted_ids" not in data or not isinstance(data["deleted_ids"], list):
                    data["deleted_ids"] = []
                if "selected_cam_id" not in data:
                    data["selected_cam_id"] = None
                self._data = data
            except Exception:
                # keep defaults if read fails
                pass

    def _save(self):
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def _find_cam(self, cam_id: int) -> Optional[Dict[str, Any]]:
        for c in self._data["cameras"]:
            if c.get("id") == cam_id:
                return c
        return None

    def _ensure_cam(self, cam_id: int) -> Dict[str, Any]:
        # Remove duplicates
        self._data["cameras"] = [c for c in self._data["cameras"] if c.get("id") != cam_id]
        cam = {
            "id": cam_id,
            "polygons": [{"coord": [], "seen": 0, "name": ""} for _ in range(self.max_polygons)]
        }
        self._data["cameras"].append(cam)
        return cam

    # --------------- public API ---------------
    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            self._maybe_reload()
            return json.loads(json.dumps(self._data))  # deep copy

    def get_polygons(self, cam_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            self._maybe_reload()
            cam = self._find_cam(cam_id)
            return json.loads(json.dumps(cam["polygons"])) if cam else []

    def set_polygons(self, cam_id: int, polygons: List[Dict[str, Any]]):
        with self._lock:
            cam = self._ensure_cam(cam_id)
            fixed: List[Dict[str, Any]] = []
            for p in polygons[: self.max_polygons]:
                fixed.append({
                    "coord": p.get("coord", []),
                    "seen": int(p.get("seen", 0)),
                    "name": str(p.get("name", "")),
                })
            while len(fixed) < self.max_polygons:
                fixed.append({"coord": [], "seen": 0, "name": ""})
            cam["polygons"] = fixed
            self._save()

    def clear_polygons(self, cam_id: Optional[int] = None):
        with self._lock:
            def empty_polys():
                return [{"coord": [], "seen": 0, "name": ""} for _ in range(self.max_polygons)]

            if cam_id is None:
                for cam in self._data["cameras"]:
                    cam["polygons"] = empty_polys()
                for d in self._data["deleted_ids"]:
                    d["polygons"] = empty_polys()
            else:
                cam = self._find_cam(cam_id)
                if cam:
                    cam["polygons"] = empty_polys()
                for d in self._data["deleted_ids"]:
                    if d.get("id") == cam_id:
                        d["polygons"] = empty_polys()
            self._save()

    # ---- selected camera by ID ----
    def get_selected_cam_id(self) -> Optional[int]:
        with self._lock:
            self._maybe_reload()
            return self._data.get("selected_cam_id")

    def set_selected_cam_id(self, cam_id: Optional[int]):
        with self._lock:
            self._data["selected_cam_id"] = cam_id
            self._save()

    # ---- camera lifecycle ----
    def mark_deleted(self, cam_id: int):
        with self._lock:
            donor = self._find_cam(cam_id)
            if donor:
                if not any(d.get("id") == cam_id for d in self._data["deleted_ids"]):
                    self._data["deleted_ids"].append({
                        "id": cam_id,
                        "polygons": json.loads(json.dumps(donor["polygons"]))
                    })
                self._data["cameras"] = [c for c in self._data["cameras"] if c.get("id") != cam_id]
            self._save()

    def adopt_or_init(self, new_id: int):
        with self._lock:
            if self._find_cam(new_id):
                return
            if self._data["deleted_ids"]:
                donor = self._data["deleted_ids"].pop(0)
                poly = json.loads(json.dumps(donor["polygons"]))
                self._ensure_cam(new_id)["polygons"] = poly
            else:
                self._ensure_cam(new_id)
            self._save()

    def remove_cam_entry(self, cam_id: int, keep_polygons=True):
        with self._lock:
            self._data["cameras"] = [c for c in self._data["cameras"] if c.get("id") != cam_id]
            self._save()
