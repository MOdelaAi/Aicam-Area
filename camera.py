import cv2
import os
import subprocess
import re 
import time
import logging
logger = logging.getLogger(name=__name__)

class CameraConnection:
    def __init__(self,width:int=640,height:int=480) -> None:
        self.size_width = width
        self.size_height = height
        self.status = self.create_camera_connection()
        logger.info(f"The camera status : {self.status}")
        

        
  
    def set_width(self,width:int=640)->None:
        self.size_width = width
    
    def set_height(self,height:int=480)->None:
        self.size_height = height
    
    def get_width(self,)->int:
        return self.size_width
    
    def get_height(self,)->int:
        return self.size_height
    
    def read_frame(self,)->None:
        success, img = self.camera.read()
        if not success:
            while True:
                logger.warning("no camera device")
                if self.create_camera_connection() == "connected successfully":
                    logger.info("connected again!")
                    break  
                time.sleep(1)
            return None
        return img   
            
    def create_camera_connection(self,)->str:
        index = self.get_number_device()
        if index != -1:
            self.camera = cv2.VideoCapture(index)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.size_width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size_height )
            if self.camera.isOpened():
                return "connected successfully"
        return "no camera"
            
    

    def get_number_device(self,)->int:
        try:
            output = os.popen("v4l2-ctl --list-devices").read()

            pattern = re.compile(r'(?P<device_name>[^\n:]+):[^\n]*(?P<content>(?:\n\s*/dev/[^\n]*)*)', re.MULTILINE)
            matches = pattern.finditer(output)

            maker = list(matches)[-1]
            split_line = maker.group('content').splitlines()
            device_name = [line.strip() for line in split_line if line.strip()]
            index = int(re.findall(r'\d+', device_name[0])[0])
            return index
        except :
            print(f"Error executing command: No camera")
            return -1      
   