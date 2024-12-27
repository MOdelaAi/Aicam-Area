from ultralytics import YOLO
from collections import defaultdict
import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.point import Point
from ultralytics.utils.files import increment_path
from ultralytics.utils.plotting import Annotator, colors
import json
import logging
logger = logging.getLogger(name=__name__)


class ModelboxProcess():
    
    def __init__(self) -> None:
        self.model = YOLO("model/person_ncnn_model",task='detect')
        self.names = self.model.names
        self.count_person = 0
        self.track_history = defaultdict(list)
        self.line_thickness=2
        self.track_thickness=2
        self.region_thickness=2
        # Polygon points , มุมซ้ายบน, มุมบนขวา, มุมล่างขวา, มุมล่างซ้าย 
        
    def __call__(self,img) :
        img_t = img.copy()
        results = self.model.track(img_t, save=False, show=False, conf=0.25,persist=True,classes=[0],iou=0.5,verbose=False)
        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu()
            track_ids = results[0].boxes.id.int().cpu().tolist()
            clss = results[0].boxes.cls.cpu().tolist()

            annotator = Annotator(img_t, line_width=self.line_thickness, example=str(self.names))
            for box, track_id, cls in zip(boxes, track_ids, clss):
                annotator.box_label(box, str(self.names[cls]), color=colors(cls, True))
                bbox_center = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2  # Bbox center

                track = self.track_history[track_id]  # Tracking Lines plot
                track.append((float(bbox_center[0]), float(bbox_center[1])))
                if len(track) > 30:
                    track.pop(0)
                points = np.hstack(track).astype(np.int32).reshape((-1, 1, 2))
                cv2.polylines(img_t, [points], isClosed=False, color=colors(cls, True), thickness=self.track_thickness)

                # Check if detection inside region
                for region in  self.counting_regions :
                    if region["polygon"].contains(Point((bbox_center[0], bbox_center[1]))):
                        region["counts"] += 1
                        self.count_person = 1

        # Draw regions (Polygons/Rectangles)
        for region in  self.counting_regions :
            region_label = str(region["counts"])
            region_color = region["region_color"]
            region_text_color = region["text_color"]

            polygon_coords = np.array(region["polygon"].exterior.coords, dtype=np.int32)
            centroid_x, centroid_y = int(region["polygon"].centroid.x), int(region["polygon"].centroid.y)

            text_size, _ = cv2.getTextSize(
                region_label, cv2.FONT_HERSHEY_SIMPLEX, fontScale=0.7, thickness=self.line_thickness
            )
            text_x = centroid_x - text_size[0] // 2
            text_y = centroid_y + text_size[1] // 2
            cv2.rectangle(
                img_t,
                (text_x - 5, text_y - text_size[1] - 5),
                (text_x + text_size[0] + 5, text_y + 5),
                region_color,
                -1,
            )
            cv2.putText(
                img_t, region_label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, region_text_color, self.line_thickness
            )
            cv2.polylines(img_t, [polygon_coords], isClosed=True, color=region_color, thickness=self.region_thickness)
        data = [0,0,0]
        # print(self.counting_regions)
        for region in self.counting_regions:  # Reinitialize count for each region
            data[int(region['name'])-1] = region["counts"]
            region["counts"] = 0
            self.count_person = 0
        return img_t,data
    
    def random_color(self):
        return (np.random.randint(0, 255), np.random.randint(0, 255), np.random.randint(0, 255))
    
    def update_polygon(self,data):
        self.counting_regions = []
        for item in data:
            # print([self.convert_coordinates(item)][0])
            self.counting_regions.append({
                    "name": f"{item['cropNO']}" ,
                    "polygon": Polygon([self.convert_coordinates(item)][0]),  
                    "counts": 0,
                    "dragging": False,
                    "region_color": self.random_color(),  # BGR Value
                    "text_color": (0, 0, 0),  # Region Text Color
                })
    
    def convert_coordinates(self,coord_dict):
        return [
            (int(float(coord_dict['topLeft'][0])), int(float(coord_dict['topLeft'][1]))),
            (int(float(coord_dict['topRight'][0])), int(float(coord_dict['topRight'][1]))),
            (int(float(coord_dict['bottomRight'][0])), int(float(coord_dict['bottomRight'][1]))),
            (int(float(coord_dict['bottomLeft'][0])), int(float(coord_dict['bottomLeft'][1])))
        ]

