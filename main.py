import os
import cv2
import time
import numpy as np
import pandas as pd
from threading import Thread

from ultralytics import YOLO,solutions

from stearming import StreamingOutput, StreamingHandler, StreamingServer
from mq_connector import get_serial, Mqtt_Connect
from button_light import LED_Notification, Button_Action
from camera import CameraConnection

from boxprocess import ModelboxProcess

# Global variables
RED_PIN = 23                # Pin num for red LED
GREEN_PIN = 18              # Pin num for yellow LED
BLUE_PIN = 15               # Pin num for green LED
BUTTON_PIN = 24             # Pin num for reset button
result = []                 # The result from processing (detection and extraction)
state = 0                   # The execution state
detected = None # The detected img in np form
mqtt = None                 # The instance of MQTT

# Connect with server
def result_sending() -> None:
    # get data from variable "result"
    global result
    global mqtt
    global state
    
    # Creates the MQTT instance and turns it on
    mqtt = Mqtt_Connect('6001', '1.0.0')
    time.sleep(5)
    state = 4

    time.sleep(5)

    # Send the result to MQTT
    while True:
        mqtt.client_publish(result)   # Send the set of result(s)
        if detected is not None:
            mqtt.line_notification(detected, result)
        time.sleep(5)

# Notify the state by 
def light_notification() -> None:
    global RED_PIN
    global GREEN_PIN
    global BLUE_PIN
    global state

    # Create the notification instance
    notify = LED_Notification(RED_PIN, GREEN_PIN, BLUE_PIN)

    while True:
        match state:
            case -1:            # un-regitered device
                notify.unregistered_SD_card()
            case 0:             # the sd card is correct (registered)
                notify.registered_SD_card()
            case 1:             # wifi is connecting or not connected
                notify.wifi_not_connected()
            case 2:             # wifi is connected
                notify.wifi_connected()
            case 3:             # the device is working
                notify.processing()
            case 4:             # the object has been detected
                notify.detected()

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


light_notice = Thread(target=light_notification,daemon=True).start()
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

        try:
            # The light notification for the device has been registered
            state = 0

            camera = CameraConnection()

            # The light notification for processing duration
            state = 3
            for i in range(2):
                
                if "wifi_config.bin" in os.listdir() and "key_config.bin" in os.listdir():
                    # Load model
                    try:
                        # Main process is here
                        # Connects to server
                        connection = Thread(target=result_sending,daemon=True).start()   
                        web_host = Thread(target=web_hosting,daemon=True).start()
                        
                        # get_setting_value = GetApiValue()
                        
                        # in_count,out_count = get_setting_value.getvalue()
                        box_model = ModelboxProcess()
                        
                        
                        while True:
                            ############## Process is Here ################
                            ###############################################
                            img = camera.read_frame()
                            if img is None:
                                print("[WARNING] No camera device!")
                                continue
                            detected = box_model(img)
                            
                            StreamingHandler.output.write(cv2.imencode('.jpg', detected)[1].tobytes())
                            count_person = box_model.count_person
                            result= [count_person]
                            
                            #################################################

                    except Exception as e:
                        print(f"The error is: {e}")

                else:
                    # The light notification for device connecting
                    state = 1

                    # Turns on BLE and connects to wifi
                    os.system("python3 connection_configuration.py")

                    # The light notification for device connected
                    state = 2
                    time.sleep(5)

        except Exception as e:
            print("The error is: {}".format(e))
            mqtt.client.loop_stop()
            mqtt.client.disconnect()
    else:
        # The light notification for copied device/wrong SD
        state = -1
        time.sleep(5)
        print("The device is not correct!")
        os.system("sudo shutdown -h now")

else:
    # The light notification for no registration device
    state = -1
    print("The device has not been registered!")
    time.sleep(20)
    os.system("sudo shutdown -h now")
