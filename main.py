#---------------------------------------------UPDATE#---------------------------------------------#
'''
    UPDATE environnment if any update except the code please write here
    variable : outside_environment = False or True
'''
#---------------------------------------------UPDATE#---------------------------------------------#

import os
import cv2
import time
import queue
import numpy as np
import pandas as pd
from threading import Thread,Event
import yaml
import logging
from ultralytics import YOLO,solutions
import subprocess
from stearming import StreamingOutput, StreamingHandler, StreamingServer
from mq_connector import get_serial, Mqtt_Connect
from button_light import LED_Notification, Button_Action
from camera import CameraConnection
from devicecare import DeviceCare
from boxprocess import ModelboxProcess
import gc
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s => %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(name=__name__)


# set que for share data
data_queue = queue.Queue()
state_queue = queue.Queue(maxsize=1)
mqtt_queue = queue.Queue()

event = Event()
WIDTH = 640
HEIGHT = 480
No_connection = False

        
# Connect with server
def result_sending():
    # get data from variable "result"
    event.wait()
    mqtt = mqtt_queue.get()
    global No_connection
    # Creates the MQTT instance and turns it on
    
    counter_reboot = 0
    last_time = time.time()
    # Send the result to MQTT
    while True:
        
        while mqtt.get_connect_flag() is True :
            state_queue.put(1)
            No_connection = True
            logger.warning("Wait for connection")
            counter_reboot +=1
            if counter_reboot ==48 :
                DeviceCare.reboot_device()
                
            time.sleep(5)
        information = data_queue.get() 
        # logger.debug(f"value {result}")
        if time.time()-last_time >= 5:
            mqtt.client_publish(information['result'])
            last_time = time.time()
            
        if detected is not None:
            mqtt.send_notification(information['img'], information['result'], information['img_by_sensordetected'],information['detected_select'])

# Notify the state by 
def light_notification():
    RED_PIN = 23                # Pin num for red LED
    GREEN_PIN = 19              # Pin num for yellow LED
    BLUE_PIN = 4                # Pin num for green LED
    # Create the notification instance
    notify = LED_Notification(RED_PIN, GREEN_PIN, BLUE_PIN)
    one_time = -2
    while True:
        state = state_queue.get()
        if one_time != state:
            if state == -1:  # un-registered device
                notify.unregistered_SD_card()
            elif state == 0:  # the sd card is correct (registered)
                notify.registered_SD_card()
            elif state == 1:  # wifi is connecting or not connected
                notify.wifi_and_server_not_connected()
            elif state == 2:  # wifi is connected
                notify.wifi_and_server_connected()
            elif state == 3:  # the object has not been detected
                notify.not_found_target()
            elif state == 4:  # the object has been detected
                notify.detected_target()
            one_time = state

# Reset button
def reset():
    BUTTON_PIN = 17     # Pin num for reset button

    # Creat the reset button instance
    btn = Button_Action(BUTTON_PIN)

    # Start the reset button action
    btn.reset_mode()


def web_hosting():
    event.wait()
    try:
        address = ('', 5000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()
    except Exception as e:
        print(f"The error is: {e}")


light_notice = Thread(target=light_notification,daemon=True).start()
reset_btn = Thread(target=reset,daemon=True).start()
connection = Thread(target=result_sending,daemon=True).start() # Connects to server
web_host = Thread(target=web_hosting,daemon=True).start() # streaming server

# Does the regist.bin exist?
    
if "config.yaml" in os.listdir():
    
    # Get the ip from current device
    current_serial = get_serial()

    with open("config.yaml", "r") as file:
        config = yaml.safe_load(file)

    device = config['Device']
    unlock_device = config['Unlock-Device']
    # If the ip in regist.bin is the same as the current device
    if  device['key_device'] == current_serial:
        if device['wifi']['status'] != True and device['key_from_server'] == None:
            # The light notification for device connecting
            state_queue.put(1)
            os.system("python3 connection.py")
            state_queue.put(2)
            gc.collect()
            
        if DeviceCare.check_wifi_and_internet_connection():
            logger.info("connection wifi")
            with open("config.yaml", "r") as file:
                config = yaml.safe_load(file)
            device = config['Device']
            try:
                # Main process is here
                camera = CameraConnection(WIDTH,HEIGHT)
                mqtt = Mqtt_Connect(device['type'], device['version'],device['key_from_server'])
                mqtt.set_current_setting()
                mqtt_queue.put(mqtt)
                
                # camera_queue.put(camera)
                mqtt.set_camera(camera=camera)
                
                # Load model
                box_model = ModelboxProcess()
                mqtt.set_box_model(model=box_model)
                
                event.set()
                while len(mqtt.get_cropCoordinates()) == 0:
                    img = camera.read_frame()
                    if img is None:
                        continue
                    StreamingHandler.output.write(cv2.imencode('.jpg', img)[1].tobytes())
                        
                box_model.update_polygon(mqtt.get_cropCoordinates())
                
                while True:
                    # ------------------------------ Process is Here ------------------------------ #
                    
                    if No_connection and mqtt.get_connect_flag() :
                        time.sleep(2)
                        continue
                    
                    if No_connection and mqtt.get_connect_flag() is False:
                        mqtt.set_current_setting()
                        No_connection = False
                        state_queue.put(2)
                        logger.info("setup again!")

                    sensorDetected,sensorselect = mqtt.get_sensorDetected()
                    img = camera.read_frame()
                    if img is None:
                        continue
                    
                    detected,result = box_model(img)
                    StreamingHandler.output.write(cv2.imencode('.jpg', detected)[1].tobytes())
                    TEMPERATURE = DeviceCare.get_cpu_temperature()
                    result[-1] = TEMPERATURE
                    if result[0]!=0 or result[1] !=0:
                        state_queue.put(4)
                    else:
                        state_queue.put(3)
                    detected_select = [0,0]
                    for i in range(2):
                        if result[i]!=0 and sensorselect[i]!=0:
                            detected_select[i] = 1
                    data_queue.put({'result':result,'img':detected,'img_by_sensordetected':None,'detected_select':detected_select})
                    # ------------------------------ END ------------------------------ #

            except Exception as e:
                mqtt.loop_stop()
                mqtt.disconnect()
                print(f"The error is: {e}")
                # DeviceCare.reboot_device()

    else:
        # The light notification for copied device/wrong SD
        # in the future the condition will be checked by api for open raspberry pi 
        state_queue.put(-1)
        logger.error("The device is not correct!")
        time.sleep(10)
        DeviceCare.reboot_device()

else:
    # The light notification for no registration device
    state_queue.put(-1)
    logger.critical("The device has not been registered!")
    time.sleep(30)
    os.system("sudo shutdown -h now")