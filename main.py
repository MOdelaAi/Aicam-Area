#---------------------------------------------UPDATE#---------------------------------------------#
'''
    UPDATE environnment if any update except the code please write here
    variable : outside_environment = False or True
'''
#---------------------------------------------UPDATE#---------------------------------------------#

import os
import cv2
import time
import numpy as np
import pandas as pd
from threading import Thread
import logging
from ultralytics import YOLO,solutions

from stearming import StreamingOutput, StreamingHandler, StreamingServer
from mq_connector import get_serial, Mqtt_Connect
from button_light import LED_Notification, Button_Action,outload_Relay
from camera import CameraConnection
from devicecare import DeviceCare
from boxprocess import ModelboxProcess
import gc
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s => %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(name=__name__)


# Global variables
RED_PIN = 23                # Pin num for red LED
GREEN_PIN = 19              # Pin num for yellow LED
BLUE_PIN = 4                # Pin num for green LED

BUTTON_PIN = 17             # Pin num for reset button
result = []                 # The result from processing (detection and extraction)
state = None                   # The execution state
detected = None # The detected img in np form
mqtt = None                 # The instance of MQTT
No_connection = False
img_by_sensordetected =None

# Connect with server
def result_sending() -> None:
    # get data from variable "result"
    global result
    global img_by_sensordetected
    global mqtt
    global state
    global No_connection
    # Creates the MQTT instance and turns it on
    mqtt = Mqtt_Connect('6003', '1.0.0')
    time.sleep(5)
    mqtt.set_current_setting()

    counter_reboot = 0
    time.sleep(5)
    # Send the result to MQTT
    
    while True:
        
        while mqtt.get_connect_flag() is True :
            state = 1
            No_connection = True
            logger.warning("Wait for connection")
            counter_reboot +=1
            if counter_reboot ==48 :
                DeviceCare.reboot_device()
            time.sleep(5)
            
        logger.debug(f"value {result}")
        mqtt.client_publish(result)
        if detected is not None:
            mqtt.send_notification(detected, result)
            
        time.sleep(5)

# Reset button
def reset():
    global BUTTON_PIN

    # Creat the reset button instance
    btn = Button_Action(BUTTON_PIN)

    # Start the reset button action
    btn.reset_mode()


def web_hosting():
    try:
        address = ('', 5000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()
    except Exception as e:
        print(f"The error is: {e}")
        
reset_btn = Thread(target=reset,daemon=True).start()

# Does the regist.bin exist?
    
if "regist.bin" in os.listdir():
    
    # Get the ip from current device
    current_serial = get_serial()

    # Get the stored ip from regist.bin
    with open('regist.bin', 'rb') as file:
        correct_serial = file.read().decode('ascii')
        file.close()

    # If the ip in regist.bin is the same as the current device
    if  correct_serial == current_serial:
        
        if "wifi_config.bin" not in os.listdir() and "key_config.bin" not in os.listdir():
            # The light notification for device connecting
            state = 1
            os.system("python3 connection.py")
            state = 2
            gc.collect()
            
        if DeviceCare.check_wifi_and_internet_connection():
            logger.info("connection wifi")
            print("first",state)
            try:
                # Main process is here
                # Connects to server
                connection = Thread(target=result_sending,daemon=True).start()
                web_host = Thread(target=web_hosting,daemon=True).start()
                
                # 320x240 px W*H
                # 640x480 px W*H
                # 1280x720 px :720p 
                
                camera = CameraConnection(640,480)
                WIDTH = camera.get_width()
                HEIGHT = camera.get_height()
                
                # Load model
                box_model = ModelboxProcess()
                mqtt.set_the_modelbox(box_model)
                img_test =  cv2.resize(cv2.imread('Untitled design (1).jpg'),(640,480))

                while True:
                    ############## Process is Here ################
                    ###############################################
                        
                    # if No_connection and mqtt.get_connect_flag() :
                    #     time.sleep(2)
                    #     continue
                    # if No_connection and mqtt.get_connect_flag() is False:
                    #     No_connection = False
                    #     logger.info("setup again!")
                    
                    # img = camera.read_frame()
                    # if img is None:
                    #     logger.warning("No camera device!")
                    #     continue
                    detected = box_model(img_test)


                    StreamingHandler.output.write(cv2.imencode('.jpg', detected)[1].tobytes())
                    TEMPERATURE = DeviceCare.get_cpu_temperature()
                    
                    
                    count_person = box_model.count_person
                    result = [TEMPERATURE]
                    
                    #################################################

            except Exception as e:
                mqtt.loop_stop()
                mqtt.disconnect()
                print(f"The error is: {e}")
                # DeviceCare.reboot_device()
            


            
    else:
        # The light notification for copied device/wrong SD
        # in the future the condition will be checked by api for open raspberry pi 
        state = -1
        logger.error("The device is not correct!")   
        time.sleep(10)
        DeviceCare.reboot_device()

else:
    # The light notification for no registration device
    state = -1
    logger.critical("The device has not been registered!")
    time.sleep(30)
    os.system("sudo shutdown -h now")
