import argparse
from typing import List, Optional, Union

import numpy as np
import torch

import norfair
from norfair import Detection, Paths, Tracker, Video
from norfair.distances import frobenius, iou

DISTANCE_THRESHOLD_BBOX: float = 0.7
DISTANCE_THRESHOLD_CENTROID: int = 30
MAX_DISTANCE: int = 10000


class YOLO:
    def __init__(self, model_name: str, device: Optional[str] = None):
        if device is not None and "cuda" in device and not torch.cuda.is_available():
            raise Exception(
                "Selected device='cuda', but cuda is not available to Pytorch."
            )
        # automatically set device if its None
        elif device is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"

        # load model
        self.model = torch.hub.load('ultralytics/yolov5', model_name, device=device)

    def __call__(
        self,
        img: Union[str, np.ndarray],
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        image_size: int = 720,
        classes: Optional[List[int]] = None
    ) -> torch.tensor:

        self.model.conf = conf_threshold
        self.model.iou = iou_threshold
        if classes is not None:
            self.model.classes = classes
        detections = self.model(img, size=image_size)
        return detections


def center(points):
    return [np.mean(np.array(points), axis=0)]

def yolo_detections_to_norfair_detections(
    yolo_detections: torch.tensor,
    track_points: str = "centroid"  # bbox or centroid
) -> List[Detection]:
    """convert detections_as_xywh to norfair detections
    """
    norfair_detections: List[Detection] = []

    if track_points == "centroid":
        detections_as_xywh = yolo_detections.xywh[0]
        for detection_as_xywh in detections_as_xywh:
            centroid = np.array(
                [
                    detection_as_xywh[0].item(),
                    detection_as_xywh[1].item()
                ]
            )
            scores = np.array([detection_as_xywh[4].item()])
            norfair_detections.append(
                Detection(points=centroid, scores=scores, label=int(detection_as_xywh[-1].item()))
            )
    elif track_points == "bbox":
        detections_as_xyxy = yolo_detections.xyxy[0]
        for detection_as_xyxy in detections_as_xyxy:
            bbox = np.array(
                [
                    [detection_as_xyxy[0].item(), detection_as_xyxy[1].item()],
                    [detection_as_xyxy[2].item(), detection_as_xyxy[3].item()]
                ]
            )
            scores = np.array([detection_as_xyxy[4].item(), detection_as_xyxy[4].item()])
            norfair_detections.append(
                Detection(points=bbox, scores=scores, label=int(detection_as_xyxy[-1].item()))
            )

    return norfair_detections


parser = argparse.ArgumentParser(description="Track objects in a video.")
parser.add_argument("files", type=str, nargs="+", help="Video files to process")
parser.add_argument("--model-name", type=str, default="yolov5m6", help="YOLOv5 model name")
parser.add_argument("--img-size", type=int, default="720", help="YOLOv5 inference size (pixels)")
parser.add_argument("--conf-threshold", type=float, default="0.25", help="YOLOv5 object confidence threshold")
parser.add_argument("--iou-threshold", type=float, default="0.45", help="YOLOv5 IOU threshold for NMS")
parser.add_argument("--classes", nargs="+", type=int, help="Filter by class: --classes 0, or --classes 0 2 3")
parser.add_argument("--device", type=str, default=None, help="Inference device: 'cpu' or 'cuda'")
parser.add_argument("--track-points", type=str, default="centroid", help="Track points: 'centroid' or 'bbox'")
args = parser.parse_args()

model = YOLO(args.model_name, device=args.device)

for input_path in args.files:
    video = Video(input_path=input_path)

    distance_function = iou if args.track_points == "bbox" else frobenius
    distance_threshold = (
        DISTANCE_THRESHOLD_BBOX
        if args.track_points == "bbox"
        else DISTANCE_THRESHOLD_CENTROID
    )

    tracker = Tracker(
        distance_function=distance_function,
        distance_threshold=distance_threshold,
    )
    paths_drawer = Paths(center, attenuation=0.01)

    for frame in video:
        yolo_detections = model(
            frame,
            conf_threshold=args.conf_threshold,
            iou_threshold=args.iou_threshold,
            image_size=args.img_size,
            classes=args.classes
        )
        detections = yolo_detections_to_norfair_detections(yolo_detections, track_points=args.track_points)
        tracked_objects = tracker.update(detections=detections)
        if args.track_points == "centroid":
            norfair.draw_points(frame, detections)
            norfair.draw_tracked_objects(frame, tracked_objects)
        elif args.track_points == "bbox":
            norfair.draw_boxes(frame, detections)
            norfair.draw_tracked_boxes(frame, tracked_objects)
        frame = paths_drawer.draw(frame, tracked_objects)
        video.write(frame)
