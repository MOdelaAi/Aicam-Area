import os
import cv2
import time
import json
import random
import yaml
import base64
import zipfile
import requests
from io import BytesIO
import paho.mqtt.client as mqtt
from devicecare import DeviceCare
import logging
import urllib3
from pprint import pprint
from datetime import datetime, time as _time
from button_light import outload_Relay

logger = logging.getLogger(name=__name__)
# Get the serial number of device
def get_serial() -> str|None:
    try:
        with open('/proc/cpuinfo', 'r') as f:               # Access cpuinfo
            for line in f:
                if line.startswith('Serial'):               # Access the line starts with the word "Serial"
                    return line.strip().split(": ")[1]      # Get the vanished serial number
    except Exception as e:
        return None
    
class Mqtt_Connect(mqtt.Client):
    def __init__(self, device_id: str, device_version: str,device_key:str):
        
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
        
        self.device_key = device_key
        # Declare server connection variables
        self.broker_address = os.getenv('BROKER')   # Set broker address: Server Connection
        self.api_server = os.getenv('APISERVER')   # Set API address: Server Connection
        self.port = int(os.getenv('PORT'))          # Set port: Server Connection
        self.api_key = os.getenv("MY_KEY") # Get API key

        self.device_id = device_id                  # Set device id: Server Connection
        self.device_version = device_version        # Set device version: Server Connection

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
        self.statusSensorOption = []
        self.statusSensorSelected = []
        self.notifyStatusSensor = []
        self.state_StatusSensor = [-1,-1]
        self.Relay = []
        self.RelayAutoMode = []
        
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
                                "/Control/Relay",                       #16
                                "/Control/RelayAutoMode",               #17 
                                "/Control/StatusSensor",                #18 
                                "/Control/StatusSensorOption",          #19 
                                "/Control/StatusSensorControl",         #20 
                                "/Control/StatusSensorTimerControl",    #21 
                                "/Control/StatusSensorNotifyMethod",    #22 
                                "/Control/StatusSensorNotifyInterval",  #23 
                                "/Control/SensorControl",               #24
                                "/Control/RequestImage",                #25
                                "/Control/SetCrop",                     #26
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
        self.connect_flag = False
        
        self.will_set(topic = self.device_key + "/Status",payload = Mqtt_Connect.create_state(self.device_key, "offline"), qos=2, retain=True)
        self.username_pw_set(username=os.getenv('USERMQ'), password=os.getenv('PASSMQ'))
        self.connect(self.broker_address, self.port)
        self.loop_start()
    
    # Get the current setting from server
    def set_current_setting(self) -> None:
                 
        
        # API url
        url = f"https://{self.api_server}/api/v2/deviceSetting/{self.device_key}/"
        headers = {'Authorization': self.api_key}
        
        # Get current setting
        response = requests.get(url, headers = headers).json()[0]
        pprint(response)
        if "error" in response:
            return None
        else:

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
            
            self.cropCoordinates = response['cropCoordinates']
            
        url_line_token = f"https://{self.api_server}/api/v2/device/linetoken/{self.device_key}"
        
        response_line_token = requests.get(url_line_token, headers=headers).json()

        if len(response_line_token) != 0:
            self.line_token = response_line_token['lineToken']
        else:
            self.line_token = ""

            
    def on_connect(self, mqttc, obj, flags, reason_code, properties): 
        print("Connected with MQTT Broker code: " + str(reason_code))
        if str(reason_code) == "Success":
            self.publish(self.device_key + "/Status", Mqtt_Connect.create_state(self.device_key, "online"), qos=2, retain=True)
            self.publish(self.device_key + "/Matching", 
                            json.dumps({'key': self.device_key,
                                        'deviceTypeID': self.device_id,
                                        'deviceVersion': self.device_version,
                                        'ipCamera': DeviceCare.get_url()}),
                            qos=2, 
                            retain=True)
            print('Mathced')
            for subscribe_topic in self.subscribe_topics:
                self.subscribe(self.device_key + subscribe_topic,qos=2)
            print('Subscribed')
            self.connect_flag = False
        else:
            logger.error(f"Failed to connect, return code {str(reason_code)}")
        
        

    def on_connect_fail(self, mqttc, obj):
        logger.error("Connection failed")

    def on_message(self, mqttc, obj, message):
        logger.info(f"Topic from ,{message.topic} Data: {message.payload.decode('utf-8')}")

        # Turns playload message from string to dictionary
        data = json.loads(message.payload.decode('utf-8'))
        
        if message.topic == self.device_key + self.subscribe_topics[0]:         # Change number of sensor
            if self.number_of_sensor_value > data['newSensorAmount']:
                self.current_setting.pop()
                self.state_notification.pop()
            elif self.number_of_sensor_value < data['newSensorAmount']:
                Newsensor = {"sensorNo":data['newSensorAmount'],'sensorSelect': 0, 'sensorCalibrateValue': 0, 'sensorValueLowLimit': 0, 'sensorValueHighLimit': 1, 'notifyMethod': [], 'notifyInterval': 1, 'sensorOption': 0, 'sensorControl': [], 'timerControlStatus': 0, 'timerControlBeginHour': [0], 'timerControlBeginMinute': [0], 'timerControlEndHour': [0], 'timerControlEndMinute': [0], 'notificationStartTime': 0}
                self.current_setting.append(Newsensor)
                self.state_notification.append("normal")
                
            self.number_of_sensor_value = data['newSensorAmount']
            
        elif message.topic == self.device_key + self.subscribe_topics[1]:       # Change value decimal
            self.current_setting[data['sensorNO'] - 1]['sensorSelect'] = data['sensorSelect']
            self.current_setting[data['sensorNO'] - 1]['decimal'] = 0
            
        elif message.topic == self.device_key + self.subscribe_topics[2]:       # Change calibrate value
            self.current_setting[data['sensorNO'] - 1]['sensorCalibrateValue'] = data['sensorCalibrateValue']
            
        elif message.topic == self.device_key + self.subscribe_topics[3]:       # Change sensor low limit
            self.current_setting[data['sensorNO'] - 1]['sensorValueLowLimit'] = data['valueSensorLowLimit']
            
        elif message.topic == self.device_key + self.subscribe_topics[4]:       # Change sensor high limit
            self.current_setting[data['sensorNO'] - 1]['sensorValueHighLimit'] = data['valueSensorHighLimit']
            
        elif message.topic == self.device_key + self.subscribe_topics[5]:       # Change sensor option
            last = self.current_setting[data['sensorNO'] - 1]['sensorOption']
            self.current_setting[data['sensorNO'] - 1]['sensorOption'] = data['sensorOption']
            if last != data['sensorOption']:
                self.state_notification[data['sensorNO'] - 1] = "normal"
                
            
        elif message.topic == self.device_key + self.subscribe_topics[6]:       # Change period status
            self.period_notification_status = data['sensorPeriodStatus']

            if data['sensorPeriodStatus']:
                self.peroid_notification_start_time = time.time()
            else:
                self.peroid_notification_start_time = 0
                
        elif message.topic == self.device_key + self.subscribe_topics[7]:       # Change period option
            self.period_notification_option = data['sensorPeriod']

            if data['sensorPeriod'] == 0:
                self.peroid_notification_start_time = 0
            else:
                self.peroid_notification_start_time = time.time()
                
        elif message.topic == self.device_key + self.subscribe_topics[8]:           # Manual capture
            if "key" in data:
                self.is_capture = True
                
        elif message.topic == self.device_key + self.subscribe_topics[9]:           # Change notification method for each value
            self.current_setting[data['sensorNo'] - 1]['notifyMethod'] = data['notifyMethod']
                
        elif message.topic == self.device_key + self.subscribe_topics[10]:          # Change notification option for each value   
            self.current_setting[data['sensorNo'] - 1]['notifyInterval'] = data['notifyInterval']
         
        elif message.topic == self.device_key + self.subscribe_topics[11]:           # Change line token    
            self.line_token = data["lineToken"]
            
        elif message.topic == self.device_key + self.subscribe_topics[12]:          # OTA UPDATE
            self.update_ota()
    
        elif message.topic == self.device_key + self.subscribe_topics[13]:          # Time set up
            self.current_setting[data['sensorNo'] - 1]['timerControlStatus'] = data['timerControlStatus']
            self.current_setting[data['sensorNo'] - 1]['timerControlBeginHour'] = data['timerControlBeginHour']
            self.current_setting[data['sensorNo'] - 1]['timerControlBeginMinute'] = data['timerControlBeginMinute']
            self.current_setting[data['sensorNo'] - 1]['timerControlEndHour'] = data['timerControlEndHour']
            self.current_setting[data['sensorNo'] - 1]['timerControlEndMinute'] = data['timerControlEndMinute']
    
        elif message.topic == self.device_key + self.subscribe_topics[14]: #Time set up
            self.notification_sensorDetected = data['sensorDetected']
    
        elif message.topic == self.device_key + self.subscribe_topics[15]: #Relay
            self.Relay[data['switchRelay']-1] = data['statusRelay']
            self.publish(self.device_key+'/ControlRelayMode',json.dumps({'key': self.device_key,
                                    'controlModeNo': data['switchRelay'],
                                    'controlModeStatus': 0}),
                        qos=2, 
                        retain=False)
            
            relayStatus = 0
            if data['statusRelay'] == True:
                relayStatus = 1

            self.publish(self.device_key+'/ControlRelay',json.dumps({'key': self.device_key,
                                            'relayNo': data['switchRelay'],
                                            'relayStatus':relayStatus}),
                        qos=2, 
                        retain=False)
            
            self.RelayAutoMode[data['switchRelay']-1]['relayAutoMode'] = False

            if self.Relay[data['switchRelay']-1] == True:
                outload_Relay.detected_selected()
            else:
                outload_Relay.not_detected_selected()

        elif message.topic == self.device_key + self.subscribe_topics[16]: #RelayAutoMode
            self.RelayAutoMode[data['relayNO']-1] = data
 
        elif message.topic == self.device_key + self.subscribe_topics[17]: #/Control/StatusSensor
            self.statusSensorSelected[data['statusSensorNo']-1] = data
            if data['statusSensorSelect'] == 0:
                self.publish(self.device_key +'/ValueStatusSensor',
                            json.dumps({"key":self.device_key,
                                        "statusNo":data['statusSensorNo'],
                                        "statusData":0})
                            ,qos=2
                            ,retain=False)
                self.state_notification_status[data['statusSensorNo']-1] = "normal"
                  
        
        elif message.topic == self.device_key + self.subscribe_topics[18]: #/Control/StatusSensorOption
            self.statusSensorOption[data['statusSensorNo']-1]['statusSensorOption'] = data['statusSensorOption']
        
        elif message.topic == self.device_key + self.subscribe_topics[19]: #/Control/StatusSensorControl
            self.statusSensorOption[data['statusSensorNo']-1]['statusSensorControl'] = data['statusSensorControl']
        
        elif message.topic == self.device_key + self.subscribe_topics[20]: #/Control/StatusSensorTimerControl
            self.statusTimerControl[data['statusSensorNo'] - 1]['timerControlStatus'] = data['timerControlStatus']
            self.statusTimerControl[data['statusSensorNo'] - 1]['timerControlBeginHour'] = data['timerControlBeginHour']
            self.statusTimerControl[data['statusSensorNo'] - 1]['timerControlBeginMinute'] = data['timerControlBeginMinute']
            self.statusTimerControl[data['statusSensorNo'] - 1]['timerControlEndHour'] = data['timerControlEndHour']
            self.statusTimerControl[data['statusSensorNo'] - 1]['timerControlEndMinute'] = data['timerControlEndMinute']
        
        elif message.topic == self.device_key + self.subscribe_topics[21]: #/Control/StatusSensorNotifyMethod
            self.notifyStatusSensor[data['statusSensorNo']-1]['notifyMethod'] = data['notifyMethod']
        
        elif message.topic == self.device_key + self.subscribe_topics[22]: #/Control/StatusSensorNotifyInterval
            self.notifyStatusSensor[data['statusSensorNo']-1]['notifyInterval'] = data['notifyInterval']
        
        elif message.topic == self.device_key + self.subscribe_topics[23]: #
            self.current_setting[data['sensorNO']-1]['sensorControl'] = data['sensorControl']
        
        elif message.topic == self.device_key + self.subscribe_topics[24]: #
            img = self.camera.read_frame()
            try:
                img = cv2.resize(img, (640, 480))
                _, buffer = cv2.imencode('.jpg', img)
                
                image_as_bytes = buffer.tobytes()
                image_as_base64 = base64.b64encode(image_as_bytes).decode('utf-8')
                self.publish(self.device_key+"/ImageResponse",payload=f"{image_as_base64}",qos=2,retain=False)
            except:
                pass
            
        elif message.topic == self.device_key + self.subscribe_topics[25]: #
            self.model_box.update_polygon(data['crops'])
            self.cropCoordinates = data['crops']
            print("write now")
        
    def on_disconnect(self, client, userdata, connect_flags, reason_code, properties):
        self.connect_flag = True
        logger.warning("disconnected OK")
 
    def update_ota(self,option = False,url = None) -> None:
        ROOT = os.path.dirname(__file__)
        
        # Disable only the specific warning
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        file_url = 'https://updatego.modela.co.th/update_aicam/AiCam-Life.zip'
        if option == True:
            file_url = url
        

        local_file = 'downloaded_file.zip'

        response = requests.get(file_url, stream=True,verify=False)
            
        try: 
            if response.status_code == 200:
                    # Open the local file in binary write mode
                    with open(local_file, 'wb') as file:
                        # Write the content of the response to the file
                        for chunk in response.iter_content(chunk_size=8192):
                            file.write(chunk)
                    logger.info(f"File downloaded successfully: {local_file}")
            else:
                logger.error(f"Failed to download file. Status code: {response.status_code}")

            if local_file.endswith('.zip'):
                with zipfile.ZipFile(local_file, 'r') as zip_ref:
                    # Extract all the contents to the specified folder
                    zip_ref.extractall(ROOT)
                    print(f"File extracted successfully to: {ROOT}")
                os.remove('downloaded_file.zip')
                logger.info("The device will reboot in 6 seconds . . . !")
                with open("config.yaml", "r") as file:
                    data = yaml.safe_load(file)  
                info = data['Device']
                info['key_device'] = self.key_device
                info['key_from_server'] = self.key_from_server
                info['wifi']['status'] = self.wifi_status
                info['wifi']['SSID'] = self.wifi_ssid
                info['wifi']['password'] = self.wifi_password
                
                with open("config.yaml", "w") as file:
                    yaml.dump(data, file, default_flow_style=False, allow_unicode=True)
                time.sleep(6)
                os.system('sudo reboot')
        
            else:
                logger.warning("The downloaded file is not a ZIP file. No extraction performed.")
        except:
            print("error")
    
    # Create state and return in json form
    @staticmethod
    def create_state(device_key:str, state:str) -> str:
        if state == "online":
            text = {
                "key": device_key,
                "Status": state,
                "WiFi":DeviceCare.Map_value(-105,-50,0,100)
            }
        else:
            text = {
                "key": device_key,
                "Status": state,
                "WiFi":0
            }
        return json.dumps(text)

    def client_publish(self, valuesList:list) -> None: 
        # Call back function returning the value in json form
        def to_json(key:str, sensorNo:int, sensorSelected:int, value:float) -> str:
            text = {
                'key': key,
                'sensorNo': sensorNo,
                'sensorSelected': sensorSelected,
                'mainNo': sensorNo,
                'mainData': value
            }
            return json.dumps(text)
        
        while len(valuesList) < self.number_of_sensor_value and self.number_of_sensor_value > 0:
            try:
                valuesList.append(0)
            except Exception as e:
                continue
        # print(self.current_setting)
        for i in range(3):
            sensorNo = self.current_setting[i]['sensorNo']
            sensorSelect = self.current_setting[i]['sensorSelect']
            if sensorSelect != 0:
                self.publish(self.device_key + '/ValueSensor', to_json(self.device_key, sensorNo, sensorSelect, valuesList[sensorSelect-1]), qos=2, retain=False)
            else:
                self.publish(self.device_key + '/ValueSensor', to_json(self.device_key, sensorNo, sensorSelect, 0), qos=2, retain=False)

    def control_switch(self,from_switch,relayNo):
        for item in from_switch:
            if self.RelayAutoMode[item-1]['relayAutoMode'] is True:
                
                if relayNo == 1:
                    self.Relay[item-1] = True
                    outload_Relay.detected_selected()
                else:
                    self.Relay[item-1] = False
                    outload_Relay.not_detected_selected()
                    
                self.publish(self.device_key+'/ControlRelay'
                             ,json.dumps({'key': self.device_key,
                                            'relayNo': item,
                                            'relayStatus': relayNo}),
                             qos=2,
                             retain=False)
                

    def control_low_hight(self,option:int,sensorControl:list,actual_value:float, value_low_limit:float, value_high_limit:float):
                    
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
                    self.control_switch(sensorControl,0)
                elif actual_value > value_high_limit:
                    self.control_switch(sensorControl,1)
            case 2:    
                if actual_value < value_low_limit:
                    self.control_switch(sensorControl,1)
                elif actual_value > value_high_limit:
                    self.control_switch(sensorControl,0)
            case 3:
                if actual_value > value_high_limit:
                    self.control_switch(sensorControl,1)
            case 4:
                if actual_value < value_low_limit:
                    self.control_switch(sensorControl,0)
            case 5:
                if actual_value < value_low_limit:
                    self.control_switch(sensorControl,1)
            case 6:
                if actual_value > value_high_limit:
                    self.control_switch(sensorControl,0)
            case _:
                    print("No case")
                    
    def control_sensor_option(self,option, detected_sensor, control_switch):
        if option == 1:  # On when detected / Off when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 0)
            else:
                self.control_switch(control_switch, 1)
        elif option == 2:  # Off when detected / On when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 1)
            else:
                self.control_switch(control_switch, 0)
        elif option == 3:  # Open when detected
            if detected_sensor == 1:
                self.control_switch(control_switch, 1)
        elif option == 4:  # Close when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 0)
        elif option == 5:  # Open when not detected
            if detected_sensor == 0:
                self.control_switch(control_switch, 1)
        elif option == 6:  # Close when detected
            if detected_sensor == 1:
                self.control_switch(control_switch, 0)

    def send_status(self,key,statusData):
        for index_statusNo in range(len(statusData)):
            self.publish(key +'/ValueStatusSensor',
                            json.dumps({"key":key,
                                        "statusNo":index_statusNo+1,
                                        "statusData":statusData[index_statusNo]})
                            ,qos=2
                            ,retain=False)
        
    def send_notification(self, image,valuesList:list,img_by_sensordetected=None,detectd_sensor=None):
        
        notify_url = 'https://notify-api.line.me/api/notify'            # Line notification URL
        LINE_HEADERS = {'Authorization':'Bearer ' + self.line_token}    # Line notification header 
        
        def to_json(key:str, type_senser:int,valueNo:int,valueSelected:int,valueData:int,status:str,wifi:float) -> str:
            
            text = {
                "key": key,
                "type": type_senser,
                "valueNo":valueNo,
                "valueSelected":valueSelected,
                "valueData":valueData,
                "status":status,
                "WiFi":wifi
                }
            
            return json.dumps(text)

        def comparison(actual_value:float, value_low_limit:float, value_high_limit:float)->str:
        
            if actual_value > value_high_limit:
                return "high"
            elif actual_value < value_low_limit:
                return "low"    
        
        def is_time_in_range(start, end, current):
            if start < end:
                return start <= current <= end
            else:  # ข้ามวัน
                return current >= start or current <= end
        
         # All of line notification
        def send_notification(key,type_senser,valueNo,valueSelected,valueData,status):
            print("send notification right now")
            wifi = DeviceCare.Map_value(-105,-50,0,100)
            for type in type_senser:
                self.publish(self.device_key +'/ValueSensorNotify',to_json(key,type,valueNo,valueSelected,valueData,status,wifi),qos=2, retain=False)

        for value_sensor in self.current_setting:
            if value_sensor['sensorSelect'] - 1 < 0 or value_sensor['sensorSelect'] > 4:
                continue
            type_senser = value_sensor['notifyMethod']
            INDEX = value_sensor['sensorSelect'] - 1
            valueNo = value_sensor['sensorNo']
            valueSelect = value_sensor['sensorSelect']
            option = value_sensor['sensorOption']
            sensorControl = value_sensor['sensorControl']
            valueData = valuesList[INDEX]
            
            if len(type_senser) != 0:
                if value_sensor['notifyInterval'] == 1: # Interval 1 ส่ง 1 ครั้ง
                    text = comparison(valueData,value_sensor['sensorValueLowLimit'],value_sensor['sensorValueHighLimit'])
                    if self.state_notification[valueNo-1] != text and text =='high':
                        send_notification(self.device_key,type_senser,valueNo,valueSelect,valueData,text)
                        self.state_notification[valueNo-1] = "high"
                        
                    elif self.state_notification[valueNo-1] != text and text =='low':
                        send_notification(self.device_key,type_senser,valueNo,valueSelect,valueData,text)
                        self.state_notification[valueNo-1] = "low"
                        
                else:  # Interval etc.
                    if time.time() - value_sensor['notificationStartTime'] >= self.value_notification_options[str(value_sensor['notifyInterval'])]:
                        text = comparison(valueData,value_sensor['sensorValueLowLimit'],value_sensor['sensorValueHighLimit'])
                        send_notification(self.device_key,type_senser,valueNo,valueSelect,valueData,text)
                        value_sensor['notificationStartTime'] = time.time()
                            
            # send by period of time for controlling switch relay
            if option != 0:
                if value_sensor["timerControlStatus"] == 1: 
                    start_time = _time(value_sensor["timerControlBeginHour"][0], value_sensor["timerControlBeginMinute"][0])  # set start time
                    end_time = _time(value_sensor["timerControlEndHour"][0], value_sensor["timerControlEndMinute"][0])   # set end time
                    current_time = datetime.now().time()
                    if is_time_in_range(start_time,end_time,current_time):
                        self.control_low_hight(option,sensorControl,valueData,value_sensor['sensorValueLowLimit'],value_sensor['sensorValueHighLimit'])
                            
                elif value_sensor["timerControlStatus"] == 0:
                        self.control_low_hight(option,sensorControl,valueData,value_sensor['sensorValueLowLimit'],value_sensor['sensorValueHighLimit'])
                        
        
        #---------------------------------------new---------------------------------------#
        if detectd_sensor is not None:
            if self.state_StatusSensor != detectd_sensor:
                self.send_status(self.device_key,detectd_sensor)
                self.state_StatusSensor = detectd_sensor
                
            for valueoption,valueselected,valueStatusSensor,valueTimerControl in zip(self.statusSensorOption,self.statusSensorSelected,self.notifyStatusSensor,self.statusTimerControl):
                selected = valueselected['statusSensorSelect']
                Index = valueoption['statusSensorNo']
                if selected != 0:
                    control_switch = valueoption['statusSensorControl']
                    option = valueoption['statusSensorOption']
                    
                    notifyMethod = valueStatusSensor['notifyMethod']
                    notifyInterval = valueStatusSensor['notifyInterval']
                    
                    status_time = valueTimerControl['timerControlStatus']
                    timerControlBeginHour = valueTimerControl['timerControlBeginHour'][0]
                    timerControlBeginMinute = valueTimerControl['timerControlBeginMinute'][0]
                    timerControlEndHour = valueTimerControl['timerControlEndHour'][0]
                    timerControlEndMinute = valueTimerControl['timerControlEndMinute'][0]
                    result =  1 if detectd_sensor[Index-1] == True else 0
                    
                    if len(notifyMethod) != 0:
                        if notifyInterval == 1: # Interval 1 ส่ง 1 ครั้ง
                            text =  "high" if detectd_sensor[Index-1] == True else "low"
                            if self.state_notification_status[Index-1] != text and text =='high':
                                send_notification(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                self.state_notification_status[Index-1]  = "high"
                                
                            elif self.state_notification_status[Index-1]  != text and text =='low':
                                send_notification(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                self.state_notification_status[Index-1]  = "low"
                        
                        else:  # Interval etc.
                            if time.time() - valueStatusSensor['notificationStartTime'] >= self.value_notification_options[str(notifyInterval)]:
                                text =  "high" if detectd_sensor[Index-1] == True else "low"
                                send_notification(self.device_key,notifyMethod,Index,selected,detectd_sensor[Index-1],text)
                                valueStatusSensor['notificationStartTime'] = time.time()
                    
                    if status_time == 1:
                        start_time = _time(timerControlBeginHour, timerControlBeginMinute)  # set start time
                        end_time = _time(timerControlEndHour, timerControlEndMinute)   # set end time
                        current_time = datetime.now().time()
                        if is_time_in_range(start_time,end_time,current_time):
                            self.control_sensor_option(option, detectd_sensor[Index-1], control_switch)
                    
                    elif status_time == 0:
                        self.control_sensor_option(option, detectd_sensor[Index-1], control_switch) 
        #---------------------------------------end---------------------------------------#
        
        # Take a Photo Send to Line
        image_set = image if img_by_sensordetected is None else img_by_sensordetected
        _, buffer = cv2.imencode('.jpg', image_set)
        image_file = BytesIO(buffer)
    
        if self.is_capture:
            logger.info("capture line image!")
            requests.post(notify_url, headers=LINE_HEADERS, files={'imageFile': ('notice.jpg', image_file, 'image/jpeg')}, data= {'message': 'Capture!'})
            self.is_capture = False
            
        if self.period_notification_status and self.period_notification_option != 0:
            print(time.time() - self.peroid_notification_start_time," ",float(self.period_time_options[str(self.period_notification_option)]))
            if time.time() - self.peroid_notification_start_time >= float(self.period_time_options[str(self.period_notification_option)]):
                requests.post(notify_url, headers=LINE_HEADERS, files={'imageFile': ('notice.jpg', image_file, 'image/jpeg')}, data= {'message': 'Period notification'})
                self.peroid_notification_start_time = time.time()
    
    def get_sensorDetected(self):
        sensorselect = [item['statusSensorSelect'] for item in self.statusSensorSelected]
        return self.notification_sensorDetected,sensorselect
    
    def set_box_model(self,model):
        self.model_box = model
        print("set model")
        
    def set_camera(self,camera):
        self.camera = camera
        
    def get_connect_flag(self):
        return self.connect_flag

    def get_cropCoordinates(self):
        return self.cropCoordinates
        