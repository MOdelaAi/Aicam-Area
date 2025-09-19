#boxprocess.py

from ultralytics import YOLO
import cv2
import numpy as np
import base64
from collections import deque, defaultdict

class ModelboxProcess:
    def __init__(self, WIDTH, HEIGHT, value: list = None, polygons=None) -> None:
        self.WIDTH = WIDTH
        self.HEIGHT = HEIGHT
        self.polygons = []

        if polygons:
            self.set_polygons(polygons)

        self.model = YOLO("model/yolo11n_ncnn_model", task='detect')
        self.detection_buffer = deque(maxlen=20)
        self.track_history = defaultdict(list)
        self.tracked_objects = {}
        self.region_counts = {"in": 0, "out": 0}
        self.polygon_counts = [0, 0]

        # Frame skipping logic
        self.frame_count = 0
        self.last_results = None   # cache last YOLO result

    def set_polygons(self, polygons):
        normalized = []
        for i, poly in enumerate(polygons[:2]):
            if isinstance(poly, dict):
                coord = poly.get("coord", [])
                name = poly.get("name", f"Polygon-{i+1}")
            else:
                coord = poly
                name = f"Polygon-{i+1}"
            normalized.append({"coord": coord, "seen": 0, "name": name})
        while len(normalized) < 2:
            normalized.append({"coord": [], "seen": 0, "name": ""})
        self.polygons = normalized

    def count_objects_in_polygons(self, results):
        self.polygon_counts = [0, 0]
        if not results or results[0].boxes is None:
            return
        boxes = results[0].boxes.xyxy.cpu().numpy()
        for box in boxes:
            x1, y1, x2, y2 = map(float, box)
            width = x2 - x1
            height = y2 - y1
            center_x = (x1 + x2) / 2
            ratio = 0.25
            v_ratio = 0.22
            new_x1 = center_x - width * ratio
            new_x2 = center_x + width * ratio
            new_y1 = y2 - height * v_ratio
            cx = (new_x1 + new_x2) / 2
            cy = y2
            points_to_check = [(new_x1, new_y1), (new_x2, new_y1), (new_x1, y2), (new_x2, y2), (cx, cy)]
            for i, poly in enumerate(self.polygons[:2]):
                if not poly["coord"]:
                    continue
                pts = np.array(poly["coord"], np.int32).reshape((-1, 1, 2))
                overlap = False
                for pt in points_to_check:
                    if cv2.pointPolygonTest(pts, pt, False) >= 0:
                        overlap = True
                        break
                if not overlap:
                    for (px, py) in poly["coord"]:
                        if new_x1 <= px <= new_x2 and new_y1 <= py <= y2:
                            overlap = True
                            break
                if overlap:
                    self.polygon_counts[i] += 1
            for i, count in enumerate(self.polygon_counts):
                self.polygons[i]["seen"] = count

    def __call__(self, img, show_regions=True, show_boxes=True):
        self.frame_count += 1
        origin_img = img.copy()

        # Run YOLO only on every 3rd frame
        if self.frame_count % 3 == 0:
            self.last_results = self.model.predict(
                origin_img, save=False, show=False, conf=0.4,
                iou=0.4, classes=[0], verbose=False, imgsz=416, half=True
            )

        results = self.last_results
        detected = origin_img.copy()

        if results:
            self.count_objects_in_polygons(results)

        if show_regions and self.polygons:
            overlay = detected.copy()
            colors = [((0, 255, 0), (0, 255, 0, 25)), ((255, 255, 0), (255, 255, 0, 25))]
            for i, poly in enumerate(self.polygons[:2]):
                if not poly["coord"]:
                    continue
                pts = np.array(poly["coord"], np.int32)
                stroke_color, fill_color = colors[i % len(colors)]
                cv2.polylines(detected, [pts], True, stroke_color, 2)
                cv2.fillPoly(overlay, [pts], fill_color[:3])
                x, y = int(pts[0][0]), int(pts[0][1])
                cv2.putText(detected, f"{poly['name']}: {poly['seen']}",
                            (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, stroke_color, 2)
            detected = cv2.addWeighted(overlay, 0.3, detected, 0.7, 0)

        if show_boxes and results and len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = (results[0].boxes.id.int().cpu().tolist()
                         if results[0].boxes.id is not None else [None] * len(boxes))
            for box, tid in zip(boxes, track_ids):
                x1, y1, x2, y2 = map(int, box)
                center_x = int((x1 + x2) / 2)
                width, height = x2 - x1, y2 - y1
                new_x1 = int(center_x - width * 0.25)
                new_x2 = int(center_x + width * 0.25)
                new_y1 = int(y2 - height * 0.22)
                inside_any = False
                for poly in self.polygons[:2]:
                    if not poly["coord"]:
                        continue
                    pts = np.array(poly["coord"], np.int32)
                    for pt in [(new_x1, new_y1), (new_x2, new_y1), (new_x1, y2), (new_x2, y2)]:
                        if cv2.pointPolygonTest(pts, pt, False) >= 0:
                            inside_any = True
                            break
                    if inside_any:
                        break
                color = (0, 0, 255) if inside_any else (255, 255, 255)
                cv2.rectangle(detected, (new_x1, new_y1), (new_x2, y2), color, 2)
                label = f"ID {tid}" if tid is not None else "obj"
                if inside_any:
                    label += " ✅"
                cv2.putText(detected, label, (new_x1, new_y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # print(self.polygon_counts)
        return detected, self.polygon_counts

    def capture_image(self, frame: np.ndarray, fmt: str = ".jpg", quality: int = 85, as_base64: bool = False):
        if frame is None:
            return None
        frame = frame.copy()
        params = []
        ext = fmt.lower()
        if ext in [".jpg", ".jpeg"]:
            quality = max(70, min(95, int(quality)))
            params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        ok, buf = cv2.imencode(ext, frame, params)
        if not ok:
            return None
        return base64.b64encode(buf).decode("utf-8") if as_base64 else bytes(buf)
