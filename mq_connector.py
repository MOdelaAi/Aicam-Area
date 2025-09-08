#mq_connector.py
import os
import cv2
import time
import json
import cloudscraper
import yaml
import zipfile
import requests
from io import BytesIO
import paho.mqtt.client as mqtt
from devicecare import DeviceCare
import logging
import numpy as np
import urllib3
import base64
from camera import CameraConnection
from pprint import pprint
from datetime import datetime, time as _time
from button_light import outload_Relay
from device_register import register_device
from logger_config import setup_logger
import webrtc_server
import re
import subprocess
from collections import defaultdict

#set logger
logger = setup_logger(__name__)
    
class Mqtt_Connect(mqtt.Client):
    def __init__(self, device_id: str, device_version: str,device_key:str,cameras:CameraConnection):
        
        
        super().__init__(client_id = device_key,callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        logger.info(f"Device ID: {device_id}, Device Version: {device_version}")
        with open("config.yaml", "r") as file:
            data = yaml.safe_load(file) 
        data = data['Device']
        
        self.key_device = data['key_device']
        self.key_from_server = data['key_from_server']
        self.wifi_status = data['wifi']['status']
        self.wifi_ssid = data['wifi']['SSID']
        self.wifi_password = data['wifi']['password']
        self.update_status = data['OTAstatus']
        
        self.device_key = device_key
        # Declare server connection variables
        self.broker_address = os.getenv('BROKER')   # Set broker address: Server Connection
        self.api_server = os.getenv('APISERVER')   # Set API address: Server Connection
        self.port = int(os.getenv('PORT'))          # Set port: Server Connection
        self.api_key = os.getenv("MY_KEY") # Get API key
        self.scraper = cloudscraper.create_scraper()
        self.device_id = device_id                  # Set device id: Server Connection
        self.device_version = device_version        # Set device version: Server Connection
        self.last_detected_time = time.time()       # Set time for send to line reset
        self.sent_person_detected = False         # Set time for send to line reset
        # Declare instance variables
        self.number_of_sensor_value = 0                         # Get number of sensor value
        self.current_setting = []                               # Get the current set up from api
        self.line_token = ""                                    # Get line token for line notification
        self.is_capture = False                                 # Get manual capture state
        self.period_notification_status = None                  # Get period notification state of all values
        self.period_notification_option = None                  # Get period notification option
        self.peroid_notification_start_time = 0                 # Set period notification start time
        self.state_notification = []                            # Set state of notification once time
        self.notification_sensorDetected  = []                  # select sensor for sending the image to line
        self.statusSensorOption = []                            # -----
        self.statusSensorSelected = []                          # -----
        self.notifyStatusSensor = []                            # -----
        self.state_StatusSensor = [-1,-1]                       # -----
        self.Relay = []                                         # -----
        self.RelayAutoMode = []                                 # -----
        self.number_cam = 0                                     # index capture image 
        self.cameras = cameras                                  # set camera for setting
        self.main_values = [[0]*11 for i in range(2)]           # set main value for each sensor
        # List of sensor main key
        self.sensor_main_key = ["sensorSelected",           # Store sensorNo, sensorSelect, decimal
                             "sensorCalibrate",             # Store sensorNo, sensorCalibrateValue
                             "sensorValueLimit",            # Store sensorNo, sensorValueLowLimit, sensorValueHighLimit
                             "notifySensor",                # Store sensorNo, notifyInterval, notifyMethod
                             "sensorValueOption",
                             "sensorTimerControl",]           # Store sensorNo, sensorOption, sensorControl

        # List of subscribe topics
        self.subscribe_topics = [
                                "/Control/UpdateValueSensorAmount",     #1 Get current sensor value amount
                                "/Control/ValueSensorDecimal",          #2 Get current decimal for specific sensor value
                                "/Control/CalibrateSensor",             #3 Get calibrate value for specific sensor value
                                "/Control/SensorValueLowLimit",         #4 Get low limit for specific sensor value
                                "/Control/SensorValueHighLimit",        #5 Get high limit for specific sensor value
                                "/Control/SensorValueOption",           #6 Get notificaton option for specific sensor value
                                "/Control/PeriodStatus",                #7 Get period status for specific sensor value
                                "/Control/Period",                      #8 Get period value for specific sensor value
                                "/Control/Capture",                     #9 Get manual capture status
                                "/Control/SensorNotifyMethod",          #10 Get notification method for each value
                                "/Control/SensorNotifyInterval",        #11 Get notification period for each value
                                "/linetoken",                           #12 Get line notification token
                                "/Update/ota",                          #13 Get new version
                                "/Control/SensorTimerControl",          #14 Get OTA state
                                "/Control/CameraDetected",              #15 Get Whenever Detected
                                "/Control/Relay",                       #16 Get Relay (button switch)
                                "/Control/RelayAutoMode",               #17 Get RelayAutoMode (toggle radio)
                                "/Control/StatusSensor",                #18 Get StatusSensor 
                                "/Control/StatusSensorOption",          #19 Get StatusSensorOption
                                "/Control/StatusSensorControl",         #20 Get StatusSensorControl
                                "/Control/StatusSensorTimerControl",    #21 Get StatusSensorTimerControl
                                "/Control/StatusSensorNotifyMethod",    #22 Get StatusSensorNotifyMethod
                                "/Control/StatusSensorNotifyInterval",  #23 Get StatusSensorNotifyInterval
                                "/Control/SensorControl",               #24 Get SensorControl
                                "/AddCamera",                           #25 Get AddCamera
                                "/DeleteCamera",                        #26 Get DeleteCamera
                                "/Control/SubValueSensor",              #27 Get SubValueSensor
                                "/Control/Restart",                     #28 Reset device
                                "/Control",                             #29 Time control type sensor
                                "/Update/optionOTA",                    #30 Get Update option
                                "/Control/RequestImage",                #31
                                "/Control/SetCrop",                     #32
                                ]              
        
        # Period notification time options
        self.period_time_options = {"0":0,              # select
                                    "1":2*60,           # every 2 minutes
                                    "2":5*60,           # every 5 minutes
                                    "3":10*60,          # every 10 minutes
                                    "4":15*60,          # every 15 minutes
                                    "5":30*60,          # every 30 minutes
                                    "6":60*60,          # every 1 hr.
                                    "7":8*60*60,        # every 8 hrs.
                                    "8":12*60*60,       # every 12 hrs.
                                    "9":24*60*60,       # every 1 day
                                    "10":7*24*60*60}    # every 7 days
        
        # Out of set point notification time option
        self.out_of_set_point_options = {"0":0,         # select
                                         "1":1*60,      # once
                                         "2":2*60,      # repeat 2 minutes
                                         "3":5*60,      # repeat 5 minutes
                                         "4":10*60,     # repeat 10 minutes
                                         "5":15*60,     # repeat 15 minutes
                                         "6":30*60,     # repeat 30 minutes
                                         "7":60*60,     # repeat 60 minutes
                                         "8":180*60     # repeat 180 minutes
                                        }
        
        # Notification interval option
        self.value_notification_options = {"1": 1,          # Once
                                           "2": 2 * 30,     # Every 1 minutes
                                           "3": 10 * 60,    # Every 10 minutes
                                           "4": 15 * 60,    # Every 15 minutes
                                           "5": 30 * 60,    # Every 30 minutes
                                           "6": 60 * 60}    # Every 1 hour

        self.seen_ppe = defaultdict(set)
        self.seen_non_ppe = defaultdict(set)

        self.topic_handlers = {
                self.device_key + self.subscribe_topics[0]: self.handle_update_value_sensor_amount,  #1 Get current sensor value amount
                self.device_key + self.subscribe_topics[1]: self.handle_sensor_notify_decimal,   #2 Get current sensor notify decimal
                self.device_key + self.subscribe_topics[2]: self.handle_sensor_calibrate_value,  #3 Get current sensor calibrate value
                self.device_key + self.subscribe_topics[3]: self.handle_sensor_value_low_limit,  #4 Get current sensor value low limit
                self.device_key + self.subscribe_topics[4]: self.handle_sensor_value_high_limit, #5 Get current sensor value high limit
                self.device_key + self.subscribe_topics[5]: self.handle_sensor_value_option,     #6 Get current sensor value option
                self.device_key + self.subscribe_topics[6]: self.handle_period_status, #7 Get period status for specific sensor value
                self.device_key + self.subscribe_topics[7]: self.handle_period_option, #8 Get period value for specific sensor value
                self.device_key + self.subscribe_topics[8]: self.handle_manual_capture, #9 Get manual capture status
                self.device_key + self.subscribe_topics[9]: self.handle_sensor_notify_method,   #10 Get notification method for each value
                self.device_key + self.subscribe_topics[10]: self.handle_sensor_notify_interval, #11 Get notification period for each value
                self.device_key + self.subscribe_topics[11]: self.handle_line_token, #12 Get line notification token
                self.device_key + self.subscribe_topics[12]: self.handle_ota_update,    #13 Get new version
                self.device_key + self.subscribe_topics[13]: self.handle_sensor_timer_control, #14 Get SensorTimerControl
                self.device_key + self.subscribe_topics[14]: self.handle_camera_detected, #15 Get Whenever Detected
                self.device_key + self.subscribe_topics[15]: self.handle_relay_control, #16 Get Relay (button switch)
                self.device_key + self.subscribe_topics[16]: self.handle_relay_auto_mode, #17 Get RelayAutoMode (toggle radio)
                self.device_key + self.subscribe_topics[17]: self.handle_status_sensor,
                self.device_key + self.subscribe_topics[18]: self.handle_status_sensor_option,
                self.device_key + self.subscribe_topics[19]: self.handle_status_sensor_control,
                self.device_key + self.subscribe_topics[20]: self.handle_status_sensor_timer_control,
                self.device_key + self.subscribe_topics[21]: self.handle_status_sensor_notify_method,
                self.device_key + self.subscribe_topics[22]: self.handle_status_sensor_notify_interval,
                self.device_key + self.subscribe_topics[23]: self.handle_sensor_control,
                self.device_key + self.subscribe_topics[24]: self.handle_add_camera,
                self.device_key + self.subscribe_topics[25]: self.handle_delete_camera,
                self.device_key + self.subscribe_topics[26]: self.handle_sub_value_sensor,
                self.device_key + self.subscribe_topics[27]: self.handle_reset_device,
                self.device_key + self.subscribe_topics[28]: self.handle_time_control,
                self.device_key + self.subscribe_topics[29]: self.handle_update_ota_option,
                self.device_key + self.subscribe_topics[30]: self.handle_request_image,  # 31
                self.device_key + self.subscribe_topics[31]: self.handle_set_crop, 
        }
        
        self.username_pw_set(username=os.getenv('USERMQ'), password=os.getenv('PASSMQ'))
        self.connect(self.broker_address, self.port)
        self.loop_start()
    
    # Get the current setting from server
    def set_current_setting(self) -> bool:
        # API url
        url = f"https://{self.api_server}/api/v2/deviceSetting/{self.device_key}/"
        headers = {'Authorization': self.api_key}
        print("="*150)
        print(f"Fetching settings with key={self.device_key}, headers={headers}")
        # Get current setting
        try:
                
            response = self.scraper.get(url, headers = headers)
            if response.status_code != 200:
                register_device()
                logger.error("No device in server,the device will reset to factory setting")
                DeviceCare.reboot_device()
            else:
                response = response.json()[0]
                # pprint(response)
                # Get the number of sensor value in database
                self.number_of_sensor_value = response['sensorAmount']

                # Get the sensor Detected 
                self.notification_sensorDetected = response['sensorCameraOption'][0]['sensorDetected']
                
                # Get the status for peroid notification
                self.period_notification_status = response['sensorCameraOption'][0]['sensorPeriodStatus']

                # Get the selected option for period notification
                self.period_notification_option = response['sensorCameraOption'][0]['sensorPeriod']

                # Set peroid notification start time
                if self.period_notification_status and self.period_notification_option != 0:
                    self.peroid_notification_start_time = time.time()
                
                # Get other value from database
                self.current_setting = []
                for sensorNo in range(1, response["sensorAmount"] + 1):
                    sensor_info = {"sensorNo": sensorNo}
                    
                    for sensor_topic in self.sensor_main_key:
                        for item in response[sensor_topic]:
                            if item["sensorNo"] == sensorNo:
                                sensor_info.update(item)
                                break
                    
                    
                    self.current_setting.append(sensor_info)
                    self.state_notification.append("normal")

                for setting in self.current_setting:
                    try:
                        if  len(setting['notifyMethod'])!= 0:
                            setting['notificationStartTime'] = time.time()
                        else:
                            setting['notificationStartTime'] = 0 
                    except Exception as e:
                        continue
                
                self.Relay = [False,False] if len(response['switchRelay']) == 0 else response['switchRelay']
                if len(self.Relay) <2:
                    self.Relay.append(False)
                    
                self.RelayAutoMode = [{'relayNo': 1, 'relayAutoMode': 0}, {'relayNo': 2, 'relayAutoMode': 0}] if len(response['relayAutoMode']) == 0 else response['relayAutoMode']
                if len(self.RelayAutoMode) <2:
                    if self.RelayAutoMode[0]['relayNo'] == 1:
                        self.RelayAutoMode.append({'relayNo': 2, 'relayAutoMode': 0})
                    else:
                        self.RelayAutoMode.append({'relayNo': 1, 'relayAutoMode': 0})
                        
                for item in self.RelayAutoMode :
                    item['relayAutoMode'] = bool(item['relayAutoMode'])
                
                self.notifyStatusSensor = response['notifyStatusSensor']
                self.statusSensorOption = response['statusSensorOption']
                self.statusSensorSelected = response['statusSensorSelected']
                self.statusTimerControl = response['statusTimerControl']
                self.state_notification_status = ["normal" for i in range(2)]
                for notify in self.notifyStatusSensor:
                    if  len(notify['notifyMethod'])!= 0:
                        notify['notificationStartTime'] = time.time()
                    else:
                        notify['notificationStartTime'] = 0 
            
                for info in response['notifySensorTimerControl']: # set time interval in value
                    self.current_setting[info['sensorNo']-1]['timerControlStatus'] = info['timerControlStatus']
                    self.current_setting[info['sensorNo']-1]['timerControlBeginHour'] = info['timerControlBeginHour']
                    self.current_setting[info['sensorNo']-1]['timerControlBeginMinute'] = info['timerControlBeginMinute']
                    self.current_setting[info['sensorNo']-1]['timerControlEndHour'] = info['timerControlEndHour']
                    self.current_setting[info['sensorNo']-1]['timerControlEndMinute'] = info['timerControlEndMinute']

                # setting cameras        
                url_setcamera = f"https://{self.api_server}/api/v2/aicam/get-camera/{self.device_key}/"
                try:
                    response_cameras = self.scraper.get(url_setcamera, headers = headers).json()
                    pprint(response_cameras)
                except:
                    logger.error("something error call setting cameras api",exc_info=True)
                
                number_cameras = response_cameras['cameraAmount']
                CAMERAs = response_cameras['cameras']
                
                url_addcamera = f"https://{self.api_server}/api/v2/aicam/add-camera"               
              
                if number_cameras == 0: # ยังไม่มีกล้องระบบจะ set กล้องให้อัตโนมัติหากเสียบกล้องไว้กับ raspberry pi
                    while True:
                        self.cameras.set_cameras_on_device()
                        cam_numbers = self.cameras.get_cameras_on_device()
                        if len(cam_numbers) != 0: # มีกล้องเสียบอยู่กับ raspberry pi 
                            for i in range(len(cam_numbers)):
                                data={"key": self.device_key,"name": f"webcam {i+1}", "type": "webcam","ip":None}
                                self.scraper.post(url_addcamera, headers=headers, data=data)
                                time.sleep(0.7)
                            break
                        time.sleep(2.5)
                else: # มีกล้องแล้วใน server เรียกใช้เพื่อ setting กล้องให้เครื่อง
                    for cam_info in CAMERAs:
                        if cam_info['type'] == 'ip':
                            self.cameras.add_ip_camera(cam_info)
                        else:
                            self.cameras.set_cameras_on_device()
                            cam_numbers = self.cameras.get_cameras_on_device()
                            if len(cam_numbers) != 0:
                                self.cameras.add_webcam_pi_camera(cam_info)
                
                if self.update_status == "success":
                    
                    with open("config.yaml", "r") as file:
                        data = yaml.safe_load(file)
                        
                    data['Device']['OTAstatus'] = None
                    
                    with open("config.yaml", "w") as file:
                        yaml.dump(data, file, default_flow_style=False, allow_unicode=True)
                    
                    payload = {"key":self.device_key,"status":"success"}
                    payload = json.dumps(payload)
                    self.publish(self.device_key+"/Update/ota/response",payload,qos=2,retain=False)

                logger.info("Setting complete")
                return True
        except Exception as e:
            logger.critical("error in set current setting",exc_info=True)
            return False
        
    def on_connect(self, mqttc, obj, flags, reason_code, properties): 
        logger.info("Connected with MQTT Broker code: " + str(reason_code))
        if str(reason_code) == "Success":
            self.publish(self.device_key + "/GetDeviceStatus", Mqtt_Connect.create_state(self.device_key, "online"), qos=2, retain=False)
            self.publish(self.device_key + "/Matching", 
                            json.dumps({'key': self.device_key,
                                        'deviceTypeID': self.device_id,
                                        'deviceSubTypeID':'1',
                                        'deviceDate':'2025-05-07',
                                        'deviceVersion': self.device_version,
                                        'ipRasberryPi': DeviceCare.get_url(),
                                        'macAddress': DeviceCare.get_mac_address()}),
                            qos=2, 
                            retain=True)
            logger.info('Mathced')
            for subscribe_topic in self.subscribe_topics:
                self.subscribe(self.device_key + subscribe_topic,qos=2)
            logger.info('Subscribed')
        else:
            logger.warning(f"Failed to connect, return code {str(reason_code)}")
        
        
    def Connection_status(self):
        try:
           self.publish(self.device_key + "/GetDeviceStatus", Mqtt_Connect.create_state(self.device_key, "online"), qos=2, retain=False)
        except:
           logger.error("error in conection",exc_info=True)

    def on_connect_fail(self, mqttc, obj):
        logger.warning("Connection failed")

    def on_message(self, mqttc, obj, message):
        logger.info(f"Topic from ,{message.topic} Data: {message.payload.decode('utf-8')}")
        try:
            # Turns playload message from string to dictionary
            data = json.loads(message.payload.decode('utf-8'))
            handler = self.topic_handlers.get(message.topic)
            if handler:
                handler(data)
            else:
                logger.warning(f"No handler for topic: {message.topic}")

        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from message: {message.topic} - {message.payload.decode('utf-8')}", exc_info=True)
        except Exception as e:
            logger.error(f"Error processing MQTT message: {message.topic} - {e}", exc_info=True)

    #0
    def handle_update_value_sensor_amount(self, data):
        """
        Handle the update value sensor amount message.
        """
        if self.number_of_sensor_value > data['newSensorAmount']:
            self.current_setting.pop()
            self.state_notification.pop()
        elif self.number_of_sensor_value < data['newSensorAmount']:
            Newsensor = {"sensorNo":data['newSensorAmount'],'sensorSelect': 0,'subSensorSelect': 0, 'sensorCalibrateValue': 0, 'sensorValueLowLimit': 0, 'sensorValueHighLimit': 1, 'notifyMethod': [], 'notifyInterval': 1, 'sensorOption': 0, 'sensorControl': [], 'timerControlStatus': 0, 'timerControlBeginHour': [0], 'timerControlBeginMinute': [0], 'timerControlEndHour': [0], 'timerControlEndMinute': [0], 'notificationStartTime': 0}
            self.current_setting.append(Newsensor)
            self.state_notification.append("normal")
            
        self.number_of_sensor_value = data['newSensorAmount']
    #1
    def handle_sensor_notify_decimal(self, data):
        self.current_setting[data['sensorNO'] - 1]['sensorSelect'] = data['sensorSelect']
        self.current_setting[data['sensorNO'] - 1]['decimal'] = 0
    #2
    def handle_sensor_calibrate_value(self, data):
        self.current_setting[data['sensorNO'] - 1]['sensorCalibrateValue'] = data['sensorCalibrateValue']
    #3
    def handle_sensor_value_low_limit(self, data):
        self.current_setting[data['sensorNO'] - 1]['sensorValueLowLimit'] = data['valueSensorLowLimit']
    #4
    def handle_sensor_value_high_limit(self, data):
        self.current_setting[data['sensorNO'] - 1]['sensorValueHighLimit'] = data['valueSensorHighLimit']
    #5
    def handle_sensor_value_option(self, data):
        last = self.current_setting[data['sensorNO'] - 1]['sensorOption']
        self.current_setting[data['sensorNO'] - 1]['sensorOption'] = data['sensorOption']
        if last != data['sensorOption']:
            self.state_notification[data['sensorNO'] - 1] = "normal"
    #6
    def handle_period_status(self, data):
        self.period_notification_status = data['sensorPeriodStatus']
        if data['sensorPeriodStatus']:
            self.peroid_notification_start_time = time.time()
        else:
            self.peroid_notification_start_time = 0
    #7
    def handle_period_option(self, data):
        self.period_notification_option = data['sensorPeriod']
        if data['sensorPeriod'] == 0:
            self.peroid_notification_start_time = 0
        else:
            self.peroid_notification_start_time = time.time()
    #8
    def handle_manual_capture(self, data):
        if "key" in data:
            self.number_cam = data['cameraNO']
            self.is_capture = True
    #9
    def handle_sensor_notify_method(self, data):
        self.current_setting[data['sensorNo'] - 1]['notifyMethod'] = data['notifyMethod']
    #10
    def handle_sensor_notify_interval(self, data):
        self.current_setting[data['sensorNo'] - 1]['notifyInterval'] = data['notifyInterval']
    #11
    def handle_line_token(self, data):
        self.line_token = data["lineToken"]
    #12
    def handle_ota_update(self):
        self.update_ota()
    #13
    def handle_sensor_timer_control(self, data):
        self.current_setting[data['sensorNo'] - 1]['timerControlStatus'] = data['timerControlStatus']
        self.current_setting[data['sensorNo'] - 1]['timerControlBeginHour'] = data['timerControlBeginHour']
        self.current_setting[data['sensorNo'] - 1]['timerControlBeginMinute'] = data['timerControlBeginMinute']
        self.current_setting[data['sensorNo'] - 1]['timerControlEndHour'] = data['timerControlEndHour']
        self.current_setting[data['sensorNo'] - 1]['timerControlEndMinute'] = data['timerControlEndMinute']
    #14
    def handle_camera_detected(self, data):
        self.notification_sensorDetected = data['sensorDetected']
    #15
    def handle_relay_control(self, data):
        relay_no = data['switchRelay']
        status = bool(data['statusRelay'])
        relay_index = relay_no - 1

        # ป้องกัน index ผิดพลาด
        if relay_index < 0 or relay_index >= len(self.Relay):
            logger.warning(f"[MANUAL] Invalid relay index: {relay_no}")
            return

        print("Manual Relay Control", data, repr(self.Relay[relay_index]))

        # ❗ ไม่ให้ manual ทำงาน ถ้า auto ยังเปิด
        if self.RelayAutoMode[relay_index]['relayAutoMode']:
            logger.info(f"[MANUAL] Relay {relay_no} is in Auto Mode — Manual command ignored")
            return

        # ✅ อัปเดตสถานะและส่ง MQTT
        self.Relay[relay_index] = status
        self.RelayAutoMode[relay_index]['relayAutoMode'] = False

        self.publish(self.device_key + '/ControlRelayMode', json.dumps({
            'key': self.device_key,
            'controlModeNo': relay_no,
            'controlModeStatus': 0
        }), qos=2, retain=False)

        self.publish(self.device_key + '/ControlRelay', json.dumps({
            'key': self.device_key,
            'relayNo': relay_no,
            'relayStatus': 1 if status else 0
        }), qos=2, retain=False)

        outload_Relay.set_state(relay_no, status)


    #16
    def handle_relay_auto_mode(self, data):
        print("RelayAutoMode", data)
        
        relay_index = data['relayNO'] - 1
        new_auto_mode = data.get('relayAutoMode', True)  # ป้องกัน key error
        
        # ป้องกัน index ผิด
        if relay_index < 0 or relay_index >= len(self.RelayAutoMode):
            logger.warning(f"[AUTO MODE] Invalid relay index: {relay_index + 1}")
            return

        self.RelayAutoMode[relay_index]['relayAutoMode'] = new_auto_mode

        # ✅ ถ้า auto ถูกปิด แล้วรีเลย์ยังเปิดอยู่ → ปิดรีเลย์ทันที
        if not new_auto_mode and self.Relay[relay_index] is True:
            logger.info(f"[AUTO MODE] Auto disabled — turning OFF relay {relay_index + 1}")
            self.Relay[relay_index] = False
            outload_Relay.set_state(relay_index + 1, False)

            self.publish(self.device_key + '/ControlRelay', json.dumps({
                'key': self.device_key,
                'relayNo': relay_index + 1,
                'relayStatus': 0
            }), qos=2, retain=False)

    #17
    def handle_status_sensor(self, data):
        self.statusSensorSelected[data['statusSensorNo']-1] = data
        if data['statusSensorSelect'] == 0:
            self.publish(self.device_key +'/ValueStatusSensor',
                        json.dumps({"key":self.device_key,
                        "statusNo":data['statusSensorNo'],
                        "statusData":0})
                        ,qos=2 ,retain=False)
            self.state_notification_status[data['statusSensorNo']-1] = "normal"

    #18
    def handle_status_sensor_option(self, data):
        self.statusSensorOption[data['statusSensorNo']-1]['statusSensorOption'] = data['statusSensorOption']

    #19
    def handle_status_sensor_control(self, data):
        self.statusSensorOption[data['statusSensorNo']-1]['statusSensorControl'] = data['statusSensorControl']

    #20
    def handle_status_sensor_timer_control(self, data):
        self.statusTimerControl[data['statusSensorNo']-1]['timerControlStatus'] = data['timerControlStatus']
        self.statusTimerControl[data['statusSensorNo']-1]['timerControlBeginHour'] = data['timerControlBeginHour']
        self.statusTimerControl[data['statusSensorNo']-1]['timerControlBeginMinute'] = data['timerControlBeginMinute']
        self.statusTimerControl[data['statusSensorNo']-1]['timerControlEndHour'] = data['timerControlEndHour']
        self.statusTimerControl[data['statusSensorNo']-1]['timerControlEndMinute'] = data['timerControlEndMinute']

    #21
    def handle_status_sensor_notify_method(self, data):
        self.notifyStatusSensor[data['statusSensorNo']-1]['notifyMethod'] = data['notifyMethod']

    #22
    def handle_status_sensor_notify_interval(self, data):
        self.notifyStatusSensor[data['statusSensorNo']-1]['notifyInterval'] = data['notifyInterval']

    #23
    def handle_sensor_control(self, data):
        self.current_setting[data['sensorNO']-1]['sensorControl'] = data['sensorControl']

    #24
    def handle_add_camera(self, data):
        CAM = data['cameras']
        if CAM['type'] == 'ip':
            self.cameras.set_cameras_on_device()
            self.cameras.add_ip_camera(CAM)
        else:
            self.cameras.add_webcam_pi_camera(CAM)

    #25
    def handle_delete_camera(self, data):
        CAM = data['cameras']
        self.cameras.del_camera(CAM)

    #26
    def handle_sub_value_sensor(self, data):
        self.current_setting[data['sensorNO']-1]['subSensorSelect'] = data['subSensorSelect']

    #27
    def handle_reset_device(self, data):
        if data['confirm']:
            DeviceCare.reboot_device()

    #28
    def handle_time_control(self, data):
        sensorNo = data['sensorNo']
        if sensorNo > 0 and sensorNo <= self.number_of_sensor_value:
            self.current_setting[sensorNo - 1]['timerControlStatus'] = data['timerControlStatus']
            self.current_setting[sensorNo - 1]['timerControlBeginHour'] = data['timerControlBeginHour']
            self.current_setting[sensorNo - 1]['timerControlBeginMinute'] = data['timerControlBeginMinute']
            self.current_setting[sensorNo - 1]['timerControlEndHour'] = data['timerControlEndHour']
            self.current_setting[sensorNo - 1]['timerControlEndMinute'] = data['timerControlEndMinute']

    #29
    def handle_update_ota_option(self, data):
        self.update_ota(option=True, url=data['urlOTA'])

    #30
    def handle_request_image(self, data):
        try:
            frames = self.cameras.read_frame()   # this returns a list
            if not frames:
                logger.warning("RequestImage: No frames captured")
                self.publish(
                    self.device_key + "/ImageResponse",
                    payload=json.dumps({"error": "no_frame"}),
                    qos=2,
                    retain=False
                )
                return

            # Take the first frame from the list
            img = frames[0]
            if img is None or not isinstance(img, np.ndarray):
                logger.warning("RequestImage: Invalid frame data")
                self.publish(
                    self.device_key + "/ImageResponse",
                    payload=json.dumps({"error": "invalid_frame"}),
                    qos=2,
                    retain=False
                )
                return

            img = cv2.resize(img, (640, 480))
            _, buffer = cv2.imencode('.jpg', img)
            image_as_base64 = base64.b64encode(buffer).decode('utf-8')

            self.publish(
                self.device_key + "/ImageResponse",
                payload=image_as_base64,
                qos=2,
                retain=False
            )
            logger.info("Sent ImageResponse via MQTT")

        except Exception:
            logger.error("Failed to handle RequestImage", exc_info=True)

    #31
    def handle_set_crop(self, data):
        try:
            self.model_box.update_polygon(data['crops'])
            self.cropCoordinates = data['crops']
            logger.info(f"Crop coordinates updated: {data['crops']}")
        except Exception:
            logger.error("Failed to handle SetCrop", exc_info=True)      
        
    def on_disconnect(self, client, userdata, connect_flags, reason_code, properties):
        logger.warning("disconnected from server")
    
    def update_ota(self, option=False, url=None) -> None:
        ROOT = os.path.dirname(__file__)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        file_url = url if option else 'https://updatego.modela.co.th/update_aicam/Aicam-PPE_v1.0.0.zip'
        local_file = 'downloaded_file.zip'

        try:
            response = requests.get(file_url, stream=True)
            if response.status_code == 200:
                with open(local_file, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                logger.info(f"✅ File downloaded: {local_file}")
            else:
                logger.warning(f"❌ Failed to download file. Status: {response.status_code}")
                return

            # ✅ Extract ZIP
            with zipfile.ZipFile(local_file, 'r') as zip_ref:
                zip_ref.extractall(ROOT)
                logger.info(f"✅ Extracted to {ROOT}")

            # ✅ Load existing config.yaml and update only required fields
            with open("config.yaml", "r") as file:
                data = yaml.safe_load(file)
            info = data.get('Device', {})
            info['key_device'] = self.key_device
            info['key_from_server'] = self.key_from_server
            info['wifi']['status'] = self.wifi_status
            info['wifi']['SSID'] = self.wifi_ssid
            info['wifi']['password'] = self.wifi_password
            
            os.remove(local_file)
            
            setup_path = os.path.join(ROOT, "setup.sh")
            if os.path.exists(setup_path):
                logger.info("🔧 setup.sh found. Running...")
                try:
                    os.chmod(setup_path, 0o755)
                    result = subprocess.run(["bash", setup_path], capture_output=True)
                    if result.returncode == 0:
                        logger.info(f"✅ setup.sh executed:\n{result.stdout.decode().strip()}")
                        os.remove(setup_path)
                        logger.info("🗑️ setup.sh removed after execution.")
                    else:
                        logger.error(f"❌ setup.sh failed: {result.stderr.decode().strip()}")
                        payload = {"key": self.device_key, "status": "failed"}
                        self.publish(self.device_key + "/Update/ota/response", json.dumps(payload), qos=2, retain=False)
                        return
                        
                except Exception as e:
                    logger.exception("❌ Exception while running setup.sh")
                    payload = {"key": self.device_key, "status": "failed"}
                    self.publish(self.device_key + "/Update/ota/response", json.dumps(payload), qos=2, retain=False)
                    return
            else:
                logger.info("ℹ️ No setup.sh found in extracted update.")

            new_version = None
            filename = file_url.split("/")[-1]  # เช่น Aicam-Human_vertical_v1.0.1.zip

            try:
                if "re" in globals():
                    match = re.search(r"_?v?(\d+\.\d+\.\d+)\.zip", filename)
                    if match:
                        new_version = match.group(1)
            except Exception:
                pass

            if not new_version:
                try:
                    filename = filename.replace(".zip", "")
                    list_parts = filename.split("_")
                    new_version = list_parts[-1].lstrip("v")
                except Exception:
                    pass

            if not new_version:
                logger.warning("⚠️ No version info found in zip filename. Keeping old version.")
            else:
                logger.info(f"✅ Extracted version from filename: {new_version}")
            info['OTAstatus'] = "success"
            if new_version:
                info['version'] = new_version

            with open("config.yaml", "w") as file:
                yaml.dump(data, file, default_flow_style=False, allow_unicode=True)
            logger.info(f"✅ config.yaml updated with version: {new_version}")

            DeviceCare.reboot_device()

        except Exception as e:
            logger.error("❌ error call update api", exc_info=True)
            payload = {"key": self.device_key, "status": "failed"}
            self.publish(self.device_key + "/Update/ota/response", json.dumps(payload), qos=2, retain=False)
      
    # Create state and return in json form
    @staticmethod
    def create_state(device_key:str, state:str) -> str:
        if state == "online":
            text = {
                "key": device_key,
                "status": True,
                "WiFi":DeviceCare.Map_value(-105,-50,0,100)
            }
        else:
            text = {
                "key": device_key,
                "status": False,
                "WiFi":0
            }
        return json.dumps(text)

    def get_main_values(self,):
        return self.main_values

    def get_camera_info(self):
        try:
            url_setcamera = f"https://{self.api_server}/api/v2/aicam/get-camera/{self.device_key}/"
            headers = {'Authorization': self.api_key}
            response_cameras = self.scraper.get(url_setcamera, headers = headers).json()
            # pprint(response_cameras)
            return response_cameras
        except:
            logger.error("something error call setting cameras api",exc_info=True)
            return

    def format_value(self, valuesList) -> None:

        return None
    
    def control_switch(self, relayNo, from_switch=None, detectObj=None):
        
        if from_switch is None or len(from_switch) == 0:
            logger.warning(f"control_switch: from_switch is None or empty - from {detectObj}")
            return

        # print("control_switch",from_switch,relayNo)
        for item in from_switch:
            if self.RelayAutoMode[item-1]['relayAutoMode'] is True:

                current_state = self.Relay[item-1]
                new_state = (relayNo >= 1)

                if current_state == new_state:
                    continue
                
                self.Relay[item-1] = new_state
                logger.info(f"Relay {item} turned {'ON' if new_state else 'OFF'} from {ppe_object.get(detectObj, 'Unknown')}")

                outload_Relay.set_state(item, new_state)
                    
                self.publish(self.device_key+'/ControlRelay',json.dumps({'key': self.device_key,
                                            'relayNo': item,
                                            'relayStatus': relayNo}),
                                qos=2, 
                                retain=False)
        
    def control_low_high(self,option:int,sensorControl:list,actual_value:float, value_low_limit:float, value_high_limit:float, detectObj=None):
                    
        '''
            option 1: Turn on when over high limit and turn off when lower low limit
            option 2: Turn off when over high limit and turn on when lower low limit
            option 3: Turn on when over high limit
            option 4: Turn off when lower low limit
            option 5: Turn on when lower low limit
            option 6: Turn off when over high limit
        '''
        match option:
            case 1:
                if actual_value < value_low_limit:
                    self.control_switch(0, sensorControl ,detectObj)
                elif actual_value > value_high_limit:
                    self.control_switch(1, sensorControl,   detectObj)
            case 2:    
                if actual_value < value_low_limit:
                    self.control_switch(1, sensorControl,   detectObj)
                elif actual_value > value_high_limit:
                    self.control_switch(0, sensorControl,   detectObj)
            case 3:
                if actual_value > value_high_limit:
                    self.control_switch(1, sensorControl,   detectObj)
            case 4:
                if actual_value < value_low_limit:
                    self.control_switch(0, sensorControl,   detectObj)
            case 5:
                if actual_value < value_low_limit:
                    self.control_switch(1, sensorControl,   detectObj)
            case 6:
                if actual_value > value_high_limit:
                    self.control_switch(0, sensorControl,  detectObj)
            case _:
                    pass

    def control_sensor_option(self, option, detected_sensor, control_switch, detectObj=None):
        if option == 1:  # On when detected / Off when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 0, detectObj)
            else:
                self.control_switch(control_switch, 1, detectObj)
        elif option == 2:  # Off when detected / On when not detected
            if detected_sensor == 1:
                self.control_switch(control_switch, 1, detectObj)
            else:
                self.control_switch(control_switch, 0, detectObj)
        elif option == 3:  # Open when detected
            if detected_sensor == 1:
                self.control_switch(control_switch, 1, detectObj)
        elif option == 4:  # Close when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 0, detectObj)
        elif option == 5:  # Open when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 1, detectObj)
        elif option == 6:  # Close when detected
            if detected_sensor == 1:
                self.control_switch(control_switch, 0, detectObj)

    def handle_relay_control_timer(self, value_sensor, detect_cond, relayControl, valueData, detectObj):
        """Handle relay control logic based on sensor conditions and timer settings"""
        if detect_cond != 0:
            if value_sensor["timerControlStatus"] == 1: 
                start_time = _time(value_sensor["timerControlBeginHour"][0], value_sensor["timerControlBeginMinute"][0])  # set start time
                end_time = _time(value_sensor["timerControlEndHour"][0], value_sensor["timerControlEndMinute"][0])   # set end time
                current_time = datetime.now().time()
                if self.is_time_in_range(start_time, end_time, current_time):
                    self.control_low_high(detect_cond, relayControl, valueData, value_sensor['sensorValueLowLimit'], value_sensor['sensorValueHighLimit'], detectObj)
            elif value_sensor["timerControlStatus"] == 0:
                self.control_low_high(detect_cond, relayControl, valueData, value_sensor['sensorValueLowLimit'], value_sensor['sensorValueHighLimit'], detectObj)

    def handle_status_sensor_relay_control(self, valueoption, valueTimerControl, detect_cond, detectd_sensor, Index, control_switch):
        """Handle status sensor relay control logic"""
        status_time = valueTimerControl['timerControlStatus']
        timerControlBeginHour = valueTimerControl['timerControlBeginHour'][0]
        timerControlBeginMinute = valueTimerControl['timerControlBeginMinute'][0]
        timerControlEndHour = valueTimerControl['timerControlEndHour'][0]
        timerControlEndMinute = valueTimerControl['timerControlEndMinute'][0]
        
        if status_time == 1:
            start_time = _time(timerControlBeginHour, timerControlBeginMinute)  # set start time
            end_time = _time(timerControlEndHour, timerControlEndMinute)   # set end time
            current_time = datetime.now().time()
            if self.is_time_in_range(start_time, end_time, current_time):
                self.control_sensor_option(detect_cond, detectd_sensor[Index-1], control_switch)
        elif status_time == 0:
            self.control_sensor_option(detect_cond, detectd_sensor[Index-1], control_switch)

    def send_status(self,key,statusData):
        for index_statusNo in range(len(statusData)):
            self.publish(key +'/ValueStatusSensor',
                            json.dumps({"key":key,
                                        "statusNo":index_statusNo+1,
                                        "statusData":statusData[index_statusNo]})
                            ,qos=2
                            ,retain=False)

    def client_publish(self, valuesList, image, detectd_sensor=None, img_by_sensordetected=None, detection_buffer=None, correct_sensors=None):
        print("client_publish", valuesList)
        """
            Format Value
            1 Camera => [[1, 0], 1] => [[frame1count1, frame1count2], totalcount]
            2 Camera => [[1, 0], [1, 0], 2] => [[frame1count1, frame1count2], [frame2count1, frame2count2], totalcount]
        """
        def comparison(actual_value:float, value_low_limit:float, value_high_limit:float)->str:
            if actual_value is None:
                return "normal"
            if actual_value > value_high_limit:
                return "high"
            elif actual_value < value_low_limit:
                return "low"
            else:
                return "normal"  
        
        def is_time_in_range(start, end, current):
            if start < end:
                return start <= current <= end
            else:  # ข้ามวัน
                return current >= start or current <= end

        def sensor_value_json(key:str, sensorNo:int, sensorSelected:int, value:float) -> str:
            text = {
                'key': key,
                'sensorNo': sensorNo,
                'sensorSelected': sensorSelected,
                'mainNo': sensorNo,
                'mainData': value
            }
            return json.dumps(text)

        def notification_json(key:str, type_senser:int,valueNo:int,valueSelected:int,valueData:int,status:str,wifi:float) -> str:
            # print(type(valueData))
            # print(key, type_senser, valueNo, valueSelected, valueData, status)
            text = {
                "key": key,
                "type": type_senser,
                "valueNo":valueNo,
                "valueSelected":valueSelected,
                "valueData":int(valueData), # from numpy to int
                "status":status,
                "WiFi":wifi
                }
            
            return json.dumps(text)

        def send_notify(key,type_senser,valueNo,valueSelected,valueData,status,image=None):
            print(f"Send notify: {key}, Type: {type_senser}, ValueNo: {valueNo}, ValueSelected: {valueSelected}, ValueData: {valueData}, Status: {status}")
            wifi = DeviceCare.Map_value(-105,-50,0,100)
            for type_sender in type_senser:
                
                if type_sender == 3 and image is not None:
                    _, buffer = cv2.imencode('.jpg', image)
                    image_file = BytesIO(buffer)
                    url_send_image = f'https://{self.api_server}/api/v2/aicam/send-camera-notifications'
                    headers = {'Authorization': self.api_key}
                    files = {
                        "imageFile": ("image.jpg", image_file, "image/jpeg"),
                    }
                    data = {
                        "key": self.device_key,
                        "cameraNO": self.number_cam+1,
                    }
                    self.scraper.post(url_send_image, headers=headers, data=data, files=files)
                else: 
                    self.publish(self.device_key +'/ValueSensorNotify',notification_json(key,type_sender,valueNo,valueSelected,valueData,status,wifi),qos=2, retain=False)
        
        self.publish(self.device_key + '/WiFiSignal',payload=json.dumps({
            'key': self.device_key,
            'WiFi': DeviceCare.Map_value(-105, -50, 0, 100)
            }), qos=2, retain=False)

        active_preset_keys = set() 

        for i in range(self.number_of_sensor_value):
            # print(f"Sensor {i}:")
            # print(f"  number_of_sensor_value: {self.number_of_sensor_value}")
            sensor_config = self.current_setting[i]
            # print(f"  sensor_config: {sensor_config}")
            sensorNo = sensor_config['sensorNo'] 
            detectObj = sensor_config['sensorSelect']
            camera = sensor_config['subSensorSelect']
            detect_cond = sensor_config['sensorOption']
            relay = sensor_config['sensorControl']
            notiType = sensor_config['notifyMethod']
            # print(f"  sensorNo: {sensorNo}, detectObj: {detectObj}, camera: {camera}")

            #camera index
            camera_no = next((i for i, d in enumerate(self.cameras.cameras)
                        if isinstance(d, dict) and d.get('cameraNO') == camera), None)

            # Handle preset configurations (10-19)
            if camera_no is not None and detectObj != 0 and camera != 0:
                frame_counts = valuesList[camera_no] if camera_no < len(valuesList) else []
                
                if detectObj == 1:
                    value = valuesList[-1]  # total
                elif detectObj == 2:
                    value = frame_counts[0] if len(frame_counts) > 0 else 0  # Area1
                elif detectObj == 3:
                    value = frame_counts[1] if len(frame_counts) > 1 else 0  # Area2
                else:
                    value = 0 

                self.publish(self.device_key + '/ValueSensor',
                            sensor_value_json(self.device_key, sensorNo, detectObj, int(value)),
                            qos=2, retain=False)

                # active relay control based on sensor conditions
                if camera != 0 and relay and isinstance(relay, list) and len(relay) > 0:
                    self.control_switch(value, relay, detectObj)

            else:
                self.publish(self.device_key + '/ValueSensor',
                            sensor_value_json(self.device_key, sensorNo, detectObj, 0),
                            qos=2, retain=False)
            
            if len(notiType) != 0:
                if sensor_config["timerControlStatus"] != 1 :
                    if sensor_config['notifyInterval'] == 1: # Interval 1 ส่ง 1 ครั้ง
                        text = comparison(value,sensor_config['sensorValueLowLimit'],sensor_config['sensorValueHighLimit'])
                        if self.state_notification[sensorNo-1] != text and text =='high':
                            send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                            self.state_notification[sensorNo-1] = "high"
                            
                        elif self.state_notification[sensorNo-1] != text and text =='low':
                            send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                            self.state_notification[sensorNo-1] = "low"
                            
                    else:  # Interval etc. ตามเวลาที่กำหนด
                        if time.time() - sensor_config['notificationStartTime'] >= self.value_notification_options[str(sensor_config['notifyInterval'])]:
                            text = comparison(value,sensor_config['sensorValueLowLimit'],sensor_config['sensorValueHighLimit'])
                            send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                            sensor_config['notificationStartTime'] = time.time()
                            
                elif sensor_config["timerControlStatus"] == 1 : # ส่งตามช่วงเวลา
                    start_time = _time(sensor_config["timerControlBeginHour"][0], sensor_config["timerControlBeginMinute"][0])  # set start time
                    end_time = _time(sensor_config["timerControlEndHour"][0], sensor_config["timerControlEndMinute"][0])   # set end time
                    current_time = datetime.now().time()
                    if is_time_in_range(start_time,end_time,current_time):
                        if sensor_config['notifyInterval'] == 1: # Interval 1 ส่ง 1 ครั้ง
                            text = comparison(value,sensor_config['sensorValueLowLimit'],sensor_config['sensorValueHighLimit'])
                            if self.state_notification[sensorNo-1] != text and text =='high':
                                send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                                self.state_notification[sensorNo-1] = "high"
                                
                            elif self.state_notification[sensorNo-1] != text and text =='low':
                                send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                                self.state_notification[sensorNo-1] = "low"

                        else:  # Interval etc. ตามเวลาที่กำหนด
                            if time.time() - sensor_config['notificationStartTime'] >= self.value_notification_options[str(sensor_config['notifyInterval'])]:
                                text = comparison(value,sensor_config['sensorValueLowLimit'],sensor_config['sensorValueHighLimit'])
                                send_notify(self.device_key,notiType,sensorNo,detectObj,value,text,image[camera_no][detect_cond])
                                sensor_config['notificationStartTime'] = time.time()

        if detectd_sensor is not None:
            print(f"Detected Sensor: {detectd_sensor}")
            if self.state_StatusSensor != detectd_sensor:
                self.send_status(self.device_key,detectd_sensor)
                self.state_StatusSensor = detectd_sensor
                
            for valueoption,valueselected,valueStatusSensor,valueTimerControl in zip(self.statusSensorOption,self.statusSensorSelected,self.notifyStatusSensor,self.statusTimerControl):
                selected = valueselected['statusSensorSelect']
                Index = valueoption['statusSensorNo']
                if selected != 0:
                    control_switch = valueoption['statusSensorControl']
                    detect_cond = valueoption['statusSensorOption']
                    
                    notifyMethod = valueStatusSensor['notifyMethod']
                    notifyInterval = valueStatusSensor['notifyInterval']
                    
                    status_time = valueTimerControl['timerControlStatus']
                    timerControlBeginHour = valueTimerControl['timerControlBeginHour'][0]
                    timerControlBeginMinute = valueTimerControl['timerControlBeginMinute'][0]
                    timerControlEndHour = valueTimerControl['timerControlEndHour'][0]
                    timerControlEndMinute = valueTimerControl['timerControlEndMinute'][0]
                    
                    if len(notifyMethod) != 0:
                        if notifyInterval == 1: # Interval 1 ส่ง 1 ครั้ง
                            text =  "high" if detectd_sensor[Index-1] == True else "low"
                            if self.state_notification_status[Index-1] != text and text =='high':
                                send_notify(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                self.state_notification_status[Index-1]  = "high"
                                
                            elif self.state_notification_status[Index-1]  != text and text =='low':
                                send_notify(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                self.state_notification_status[Index-1]  = "low"
                        
                        else:  # Interval etc.
                            if time.time() - valueStatusSensor['notificationStartTime'] >= self.value_notification_options[str(notifyInterval)]:
                                text =  "high" if detectd_sensor[Index-1] == True else "low"
                                send_notify(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                valueStatusSensor['notificationStartTime'] = time.time()

        # Take a Photo Send to Line
        try:
            if self.number_cam !=0:
                image_set = image[self.number_cam - 1][0]
                image_prepared = image_set.copy()
                _, buffer = cv2.imencode('.jpg', image_prepared)
                image_file = BytesIO(buffer)

                url_send_image = f'https://{self.api_server}/api/v2/aicam/send-camera-notifications'
                headers = {'Authorization': self.api_key}
                files = {
                    "imageFile": ("image.jpg", image_file, "image/jpeg"),
                }
                data = {
                    "key": self.device_key,
                    "cameraNO": self.number_cam,
                }
                if self.is_capture:
                    logger.info("capture line image!")
                    self.scraper.post(url_send_image, headers=headers, data=data, files=files)
                    self.is_capture = False
                
                if self.period_notification_status and self.period_notification_option != 0:
                    if time.time() - self.peroid_notification_start_time >= float(self.period_time_options[str(self.period_notification_option)]):
                        self.scraper.post(url_send_image, headers=headers, data=data, files=files)
                        self.peroid_notification_start_time = time.time()
                        
            if len(self.notification_sensorDetected) != 0:
                if any(detection_buffer):
                    self.last_detected_time = time.time()
                    if not self.sent_person_detected and img_by_sensordetected[self.number_cam] is not None and correct_sensors[self.number_cam] == self.notification_sensorDetected[0]:
                        _, buffer = cv2.imencode('.jpg', img_by_sensordetected[self.number_cam])
                        image_file = BytesIO(buffer)
                        url_send_image = f'https://{self.api_server}/api/v2/aicam/send-camera-notifications'
                        headers = {'Authorization': self.api_key}
                        files = {
                            "imageFile": ("image.jpg", image_file, "image/jpeg"),
                        }
                        data = {
                            "key": self.device_key,
                            "cameraNO": self.number_cam+1,
                        }
                        self.scraper.post(url_send_image, headers=headers, data=data, files=files)
                        self.sent_person_detected = True
                else:
                    if self.sent_person_detected and (time.time() - self.last_detected_time > 5):
                        self.sent_person_detected = False
                        
        except Exception as e:
            logger.error(f"error when send image to line {e}",exc_info=True)
    
    def get_sensorDetected(self):
        sensorselect = [item['statusSensorSelect'] for item in self.statusSensorSelected]
        return self.notification_sensorDetected,sensorselect

    def del__cameras(self):
        self.cameras.del_all_camera()

    def set_box_model(self,model):
        self.model_box = model
        print("set model")

    def get_connect_flag(self):
        return self.connect_flag

    def get_cropCoordinates(self):
        return self.cropCoordinates
        
if __name__ == '__main__':
    '''
    this program it debug and test only!
    '''
    pass




