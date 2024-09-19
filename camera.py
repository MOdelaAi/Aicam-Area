import cv2
import os
import subprocess
import re 
import time

class CameraConnection:
    def __init__(self,) -> None:
        self.status = self.create_camera_connection()
        print("[INFO] The camera status : ", self.status)
        self.size_width = 640
        self.size_height = 480
        
  
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
                print("no device")
                if self.create_camera_connection() == "connected successfully":
                    print("[INFO] connected again!")
                    break  
                time.sleep(1)
            return None
        return img   
            
    def create_camera_connection(self,)->str:
        index = self.get_number_device()
        if index != -1:
            self.camera = cv2.VideoCapture(index)
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
   