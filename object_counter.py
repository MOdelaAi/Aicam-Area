# Ultralytics YOLO 🚀, AGPL-3.0 license

from collections import defaultdict
import cv2
from ultralytics.utils.checks import check_imshow, check_requirements
from ultralytics.utils.plotting import Annotator, colors
check_requirements("shapely>=2.0.0")
from shapely.geometry import LineString, Point, Polygon


class ObjectCounter:
    def __init__(
        self,
        names,
        reg_pts=None,
        count_reg_color=(255, 0, 255),
        count_txt_color=(0, 0, 0),
        count_bg_color=(255, 255, 255),
        line_thickness=2,
        track_thickness=2,
        view_img=False,
        view_in_counts=True,
        view_out_counts=True,
        draw_tracks=False,
        track_color=None,
        region_thickness=5,
        line_dist_thresh=15,
        cls_txtdisplay_gap=50,
    ):
        self.is_drawing = False
        self.selected_point = None
        self.reg_pts = [(20, 400), (1260, 400)] if reg_pts is None else reg_pts
        self.line_dist_thresh = line_dist_thresh
        self.counting_region = None
        self.region_color = count_reg_color
        self.region_thickness = region_thickness
        self.im0 = None
        self.tf = line_thickness
        self.view_img = view_img
        self.view_in_counts = view_in_counts
        self.view_out_counts = view_out_counts
        self.names = names
        self.annotator = None
        self.window_name = "Ultralytics YOLOv8 Object Counter"
        self.in_counts = 0
        self.out_counts = 0
        self.class_wise_count = {}
        self.count_txt_thickness = 0
        self.count_txt_color = count_txt_color
        self.count_bg_color = count_bg_color
        self.cls_txtdisplay_gap = cls_txtdisplay_gap
        self.fontsize = 0.6
        self.track_history = defaultdict(list)
        self.track_thickness = track_thickness
        self.draw_tracks = draw_tracks
        self.track_color = track_color
        self.env_check = check_imshow(warn=True)
        self.value_counter = [0 for _ in range(12)]

        if len(self.reg_pts) == 2:
            print("Line Counter Initiated.")
            self.counting_region = LineString(self.reg_pts)
        elif len(self.reg_pts) >= 3:
            print("Polygon Counter Initiated.")
            self.counting_region = Polygon(self.reg_pts)
        else:
            print("Invalid Region points provided, region_points must be 2 for lines or >= 3 for polygons.")
            print("Using Line Counter Now")
            self.counting_region = LineString(self.reg_pts)

    def extract_and_process_tracks(self, tracks):
        self.annotator = Annotator(self.im0, self.tf, self.names)
        self.annotator.draw_region(reg_pts=self.reg_pts, color=self.region_color, thickness=self.region_thickness)

        if tracks[0].boxes.id is not None:
            boxes = tracks[0].boxes.xyxy.cpu()
            clss = tracks[0].boxes.cls.cpu().tolist()
            track_ids = tracks[0].boxes.id.int().cpu().tolist()

            for box, track_id, cls in zip(boxes, track_ids, clss):
                if self.names[cls] not in self.class_wise_count:
                    self.class_wise_count[self.names[cls]] = {"IN": self.value_counter[4], "OUT": self.value_counter[5]}

                track_line = self.track_history[track_id]
                track_line.append(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
                if len(track_line) > 30:
                    track_line.pop(0)

                if self.draw_tracks:
                    self.annotator.draw_centroid_and_tracks(
                        track_line,
                        color=self.track_color or colors(int(track_id), True),
                        track_thickness=self.track_thickness,
                    )

                if len(track_line) > 1:
                    prev_position = track_line[-2]
                    curr_position = track_line[-1]

                    if len(self.reg_pts) == 2:
                        A, B = self.reg_pts[0], self.reg_pts[1]

                        def side(p):
                            return (B[0] - A[0]) * (p[1] - A[1]) - (B[1] - A[1]) * (p[0] - A[0])

                        prev_side = side(prev_position)
                        curr_side = side(curr_position)

                        if prev_side * curr_side < 0:
                            if curr_side > prev_side:
                                self.out_counts += 1
                                self.value_counter[1] += 1
                                self.value_counter[3] += 1
                                self.value_counter[5] += 1
                                self.value_counter[7] += 1
                                self.value_counter[9] += 1
                                self.class_wise_count[self.names[cls]]["OUT"] = self.value_counter[5]
                            else:
                                self.in_counts += 1
                                self.value_counter[0] += 1
                                self.value_counter[2] += 1
                                self.value_counter[4] += 1
                                self.value_counter[6] += 1
                                self.value_counter[8] += 1
                                self.class_wise_count[self.names[cls]]["IN"] = self.value_counter[4]

        labels_dict = {}
        for key, value in self.class_wise_count.items():
            if value["IN"] != 0 or value["OUT"] != 0:
                if not self.view_in_counts and not self.view_out_counts:
                    continue
                elif not self.view_in_counts:
                    labels_dict[str.capitalize(key)] = f"OUT {value['OUT']}"
                elif not self.view_out_counts:
                    labels_dict[str.capitalize(key)] = f"IN {value['IN']}"
                else:
                    labels_dict[str.capitalize(key)] = f"IN {value['IN']} OUT {value['OUT']}"

        if labels_dict:
            self.annotator.display_analytics(self.im0, labels_dict, self.count_txt_color, self.count_bg_color, 10)



    def start_counting(self, im0, tracks):
        self.im0 = im0
        self.extract_and_process_tracks(tracks)
        return self.im0


if __name__ == "__main__":
    classes_names = {0: "person", 1: "car"}
    ObjectCounter(classes_names)
