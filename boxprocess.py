from ultralytics import YOLO, solutions
import cv2
import base64
from datetime import datetime
from collections import deque, defaultdict
import numpy as np
from ultralytics.utils.plotting import colors

class ModelboxProcess:
    def __init__(self, WIDTH, HEIGHT, value: list = None, polygons=None) -> None:
        self.WIDTH = WIDTH
        self.HEIGHT = HEIGHT
        self.polygons = []

        # normalize polygons on init
        if polygons:
            self.set_polygons(polygons)

        self.model = YOLO("model/person_ncnn_model", task='detect')
        self.counter = solutions.ObjectCounter(model=self.model)

        self.counter.names = self.model.names
        self.counter.line_thickness = 2
        self.counter.draw_tracks = True
        self.counter.count_reg_color = (67, 238, 116)

        if value is not None:
            self.counter.value_counter = value

        self.detection_buffer = deque(maxlen=20)
        self.track_history = defaultdict(list)
        self.tracked_objects = {}
        self.region_counts = {"in": 0, "out": 0}

        self.polygon_counts = [0, 0]  # up to 2 zones

    # ---------------- Polygon Handling ---------------- #
    def set_polygons(self, polygons):
        """Normalize polygons into dict form"""
        normalized = []
        for i, poly in enumerate(polygons[:2]):  # max 2
            if isinstance(poly, dict):
                coord = poly.get("coord", [])
                name = poly.get("name", f"Polygon-{i+1}")
            else:  # plain list of coords
                coord = poly
                name = f"Polygon-{i+1}"
            normalized.append({"coord": coord, "seen": 0, "name": name})

        # pad to 2
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

            # corners of the bbox
            box_pts = [
                (x1, y1),
                (x2, y1),
                (x2, y2),
                (x1, y2)
            ]

            for i, poly in enumerate(self.polygons[:2]):
                if not poly["coord"]:
                    continue

                pts = np.array(poly["coord"], np.int32).reshape((-1, 1, 2))

                # check if any bbox corner is inside polygon
                overlap = any(cv2.pointPolygonTest(pts, (float(px), float(py)), False) >= 0 
                            for (px, py) in box_pts)

                # also check if any polygon vertex is inside bbox (optional, stronger collision)
                if not overlap:
                    for (px, py) in poly["coord"]:
                        if x1 <= px <= x2 and y1 <= py <= y2:
                            overlap = True
                            break

                if overlap:
                    self.polygon_counts[i] += 1

        # update "seen"
        for i, count in enumerate(self.polygon_counts):
            self.polygons[i]["seen"] = count


    def __call__(self, img, show_regions=True, show_boxes=True):
        origin_img = img.copy()
        results = self.model.predict(
                    origin_img,
                    save=False,
                    show=False,
                    conf=0.6,
                    iou=0.4,
                    classes=[0],   # person only
                    verbose=False
                )

        detected = origin_img.copy()
        self.count_objects_in_polygons(results)

        # ---------------- Draw polygons ---------------- #
        if show_regions:
            overlay = detected.copy()
            colors = [
                ((0, 255, 0),   (0, 255, 0, 25)),   # green stroke + fill
                ((255, 255, 0), (255, 255, 0, 25)), # yellow stroke + fill
            ]

            for i, poly in enumerate(self.polygons[:2]):
                if not poly["coord"]:
                    continue
                pts = np.array(poly["coord"], np.int32)
                stroke_color, fill_color = colors[i % len(colors)]

                cv2.polylines(detected, [pts], True, stroke_color, 2)
                cv2.fillPoly(overlay, [pts], fill_color[:3])

                x, y = int(pts[0][0]), int(pts[0][1])
                cv2.putText(detected, f"{poly['name']}: {poly['seen']}",
                            (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, stroke_color, 2)

            detected = cv2.addWeighted(overlay, 0.3, detected, 0.7, 0)

        # ---------------- Draw bounding boxes ---------------- #
        if show_boxes and len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = (results[0].boxes.id.int().cpu().tolist()
                        if results[0].boxes.id is not None else [None] * len(boxes))

            for box, tid in zip(boxes, track_ids):
                x1, y1, x2, y2 = map(int, box)
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)

                # check if inside any polygon
                inside_any = False
                for poly in self.polygons[:2]:
                    if not poly["coord"]:
                        continue
                    pts = np.array(poly["coord"], np.int32)
                    if cv2.pointPolygonTest(pts, (cx, cy), False) >= 0:
                        inside_any = True
                        break

                color = (0, 0, 255) if inside_any else (255, 255, 255)

                cv2.rectangle(detected, (x1, y1), (x2, y2), color, 2)
                label = f"ID {tid}" if tid is not None else "obj"
                if inside_any:
                    label += " ✅"
                cv2.putText(detected, label, (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # draw center point
                # cv2.circle(detected, (cx, cy), 4, color, -1)

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

        if as_base64:
            return base64.b64encode(buf).decode("utf-8")
        return bytes(buf)

