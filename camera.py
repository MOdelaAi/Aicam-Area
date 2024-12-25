import cv2
import os
import re
import time
import logging
import base64
from picamera2 import Picamera2
from threading import Thread

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s => %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

logging.getLogger('picamera2').setLevel(logging.CRITICAL)
logger = logging.getLogger(name=__name__)

class CameraConnection:
    def __init__(self, width: int = 640, height: int = 480) -> None:
        self.size_width = width
        self.size_height = height
        self.status = self.create_camera_connection()
        logger.info(f"The camera status: {self.status}")

    def set_width(self, width: int = 640) -> None:
        self.size_width = width

    def set_height(self, height: int = 480) -> None:
        self.size_height = height

    def get_width(self) -> int:
        return self.size_width

    def get_height(self) -> int:
        return self.size_height
    
    def cap_image(self)->None:
        if 'webcam' in self.status:
            ret, frame = self.camera.read()
            if ret:
                _, buffer = cv2.imencode('.jpg', frame)
                
        elif 'picamera' in self.status:
            buffer = self.camera.capture_file('captured_image.jpg')
            
        image_as_bytes = buffer.tobytes()
        image_as_base64 = base64.b64encode(image_as_bytes).decode('utf-8')
        return image_as_base64
        
    def read_frame(self)->None:
        if self.status == 'connected webcam successfully':
            success, img = self.camera.read()
            if not success:
                self.camera.release()
                self.retry_connection()
                return None
        else:
            try:
                img = self.camera.capture_array()
            except Exception as e:
                logger.error("Error capturing frame from Picamera2", exc_info=e)
                self.camera.stop()
                self.retry_connection()
                return None

            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        return img

    def create_camera_connection(self) -> str:
        try:
            index = self.get_number_device()
            self.camera = cv2.VideoCapture(index)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.size_width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size_height)
            if self.camera.isOpened():
                return "connected webcam successfully"
        except Exception as e:
            logger.error("Cannot connect to webcam", exc_info=e)

        try:
            self.camera = Picamera2()
            self.status = "connected picamera successfully"
            camera_config = self.camera.create_still_configuration(
                main={"size": (self.size_width, self.size_height)}
            )
            self.camera.configure(camera_config)
            self.camera.start()
            return self.status
        except Exception as e:
            logger.error("Cannot connect to Picamera2", exc_info=e)

        return "no camera"

    def get_number_device(self) -> int:
        try:
            output = os.popen("v4l2-ctl --list-devices").read()
            pattern = re.compile(r'(?P<device_name>[^\n:]+):[^\n]*(?P<content>(?:\n\s*/dev/[^\n]*)*)', re.MULTILINE)
            matches = pattern.finditer(output)

            last_match = list(matches)[-1]
            split_lines = last_match.group('content').splitlines()
            device_name = [line.strip() for line in split_lines if line.strip()]
            index = int(re.findall(r'\d+', device_name[0])[0])
            return index
        except Exception as e:
            logger.error("Error finding camera device", exc_info=e)
            return -1

    def retry_connection(self):
        while True:
            logger.warning("Retrying camera connection...")
            if 'successfully' in self.create_camera_connection():
                logger.info("Camera reconnected!")
                break
            time.sleep(1)
