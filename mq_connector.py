import os
import cv2
import time
import json
import random
import zipfile
import requests
import paho.mqtt.client as mqtt
from urllib.parse import urlparse
import logging

from pprint import pprint

# Get the serial number of device
def get_serial() -> str|None:
    try:
        with open('/proc/cpuinfo', 'r') as f:               # Access cpuinfo
            for line in f:
                if line.startswith('Serial'):               # Access the line starts with the word "Serial"
                    return line.strip().split(": ")[1]      # Get the vanished serial number
    except Exception as e:
        return None

# MQTT Connect class
class Mqtt_Connect:
    
    # Class initailization
    def __init__(self,device_id:str, device_version:str) -> None:
        # Get the key from key_config.bin
       
        with open("key_config.bin", "rb") as file:
            self.device_key = file.read().decode('ascii')
            file.close()
        
        
        # Declare server connection variables
        self.broker_address = os.getenv('BROKER')   # Set broker address: Server Connection
        self.port = int(os.getenv('PORT'))          # Set port: Server Connection
        self.device_id = device_id                  # Set device id: Server Connection
        self.device_version = device_version        # Set device version: Server Connection
        
        
        # Set camera local host: Server Connection
        url= f'http://{os.popen("hostname -I").read().strip()}'
        url_parts = url.split(" ")
        first_url = url_parts[0]
        parsed_url = urlparse(first_url)
        self.ip_camera = f"{parsed_url.scheme}://{parsed_url.hostname}:5000/video_feed" 
        print("[INFO] YOUR URL: ",self.ip_camera)
        # Create client id
        self.client_id = self.device_key

        # Declare instance variables
        self.number_of_sensor_value = 0                         # Get number of sensor value
        self.current_setting = []                               # Get the current set up from api
        self.line_token = ""                                    # Get line token for line notification
        self.is_capture = False                                 # Get manual capture state
        self.period_notification_status = None                  # Get period notification state of all values
        self.period_notification_option = None                  # Get period notification option
        self.peroid_notification_start_time = 0                 # Set period notification start time
        self.out_of_set_point_notification_status = None        # Get out of set point notification state of all values
        self.out_of_set_point_notification_option = None        # Get out of set point notificaotin option
        self.out_of_set_point_notification_start_time = 0       # Set out of set point notification start time

        # List of sensor main key
        self.sensor_main_key = ["sensorSelected",           # Store sensorNo, sensorSelect, decimal
                             "sensorCalibrate",             # Store sensorNo, sensorCalibrateValue
                             "sensorValueLimit",            # Store sensorNo, sensorValueLowLimit, sensorValueHighLimit
                             "notifySensor",                # Store sensorNo, notifyInterval, notifyMethod
                             "sensorValueOption"]           # Store sensorNo, sensorOption, sensorControl

        # List of subscribe topics
        self.subscribe_topics = ["/Control/UpdateValueSensorAmount",    # Get current sensor value amount
                                "/Control/ValueSensorDecimal",          # Get current decimal for specific sensor value
                                "/Control/CalibrateSensor",             # Get calibrate value for specific sensor value
                                "/Control/SensorValueLowLimit",         # Get low limit for specific sensor value
                                "/Control/SensorValueHighLimit",        # Get high limit for specific sensor value
                                "/Control/SensorValueOption",           # Get notificaton option for specific sensor value
                                "/Control/PeriodStatus",                # Get period status for specific sensor value
                                "/Control/Period",                      # Get period value for specific sensor value
                                "/Control/OutOfSetPointStatus",         # Get out of set point status for specific sensor value
                                "/Control/OutOfSetPoint",               # Get out of set point value for specific sensor value
                                "/Control/Capture",                     # Get manual capture status
                                "/Control/SensorNotifyMethod",          # Get notification method for each value
                                "/Control/SensorNotifyInterval",        # Get notification period for each value
                                "/linetoken",                           # Get line notification token
                                "/Update/ota"]                          # Get OTA state
        
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
                                           "2": 2 * 60,     # Every 2 minutes
                                           "3": 10 * 60,    # Every 10 minutes
                                           "4": 15 * 60,    # Every 15 minutes
                                           "5": 30 * 60,    # Every 30 minutes
                                           "6": 60 * 60}    # Every 1 hour

        # Connect to server by 
        self.client = mqtt.Client(client_id=self.client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)     # Initialize the MQTT client with a specific client ID
        self.client.username_pw_set(username=os.getenv('USERMQ'),password=os.getenv('PASSMQ'))
        self.client_on_connect()
        # self.client.on_connect = self.on_connect                # Set callback functions for connection
        self.client.on_disconnect = self.on_disconnect          # Set callback functions for disconnection
        self.client.on_message = self.on_message                # Set callback functions for message reception

        # Set Last Will and Testament (LWT) message for unexpected disconnection
        self.client.will_set(self.device_key + "/Status", Mqtt_Connect.create_state(self.device_key, "offline"), qos=1, retain=True)

        # Connect to the MQTT broker using the specified address and port
        self.client.connect(self.broker_address, self.port)
        
        # Start the network loop in a new thread
        self.client.loop_start()

    # Get the current setting from server
    def set_current_setting(self) -> None:
                 
        # Get API key
        api_key = os.getenv("MY_KEY")

        # API url
        url = f"http://{self.broker_address}:8080/api/v2/deviceSetting/{self.device_key}/camera"
        headers = {'Authorization': api_key}
        
        # Get current setting
        response = requests.get(url, headers = headers).json()
        pprint(response)

        if "error" in response:
            return None
        else:

            # Get the number of sensor value in database
            self.number_of_sensor_value = response['sensorAmount']

            # Get the status for peroid notification
            self.period_notification_status = response['sensorCameraOption'][0]['sensorPeriodStatus']

            # Get the selected option for period notification
            self.period_notification_option = response['sensorCameraOption'][0]['sensorPeriod']

            # Set peroid notification start time
            if self.period_notification_status and self.period_notification_option != 0:
                self.peroid_notification_start_time = time.time()

            # Get the notification status for out of set point
            self.out_of_set_point_notification_status = response['sensorCameraOption'][0]['sensorOutOfSetPointStatus']
            
            # Get the notification status for out of set point
            self.out_of_set_point_notification_option = response['sensorCameraOption'][0]['sensorOutOfSetPoint']

            # Set out of set point start time
            if self.out_of_set_point_notification_status and self.out_of_set_point_notification_option != 0:
                self.out_of_set_point_notification_start_time = time.time()

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

            for setting in self.current_setting:
                try:
                    if 2 in setting['notifyMethod']:
                        setting['notificationStartTime'] = time.time()
                    else:
                        setting['notificationStartTime'] = 0 
                except Exception as e:
                    continue

        url_line_token = f"http://{self.broker_address}:8080/api/v2/device/linetoken/{self.device_key}"
        
        response_line_token = requests.get(url_line_token, headers=headers).json()

        if len(response_line_token) != 0:
            self.line_token = response_line_token['lineToken']
        else:
            self.line_token = ""
        
        

    # Set broker address
    def set_broker_address(self, new_broker_address:str) -> None:
        self.broker_address = new_broker_address
        self.reconnect()

    # Get current broker address
    def get_broker_address(self) -> str:
        return self.broker_address
    
    # Set device_key
    def set_device_key(self, new_device_key:str) -> None:
        self.device_key = new_device_key
        self.reconnect()

    # Get current device_key
    def get_device_key(self) -> str:
        return self.device_key
    
    # Set port
    def set_port(self, new_port:int) -> None:
        self.port = new_port
        self.reconnect()

    # Get current port
    def get_port(self) -> int:
        return self.port

    # Get current client id
    def get_client_id(self) -> str:
        return self.client_id

    # Create state and return in json form
    @staticmethod
    def create_state(device_key:str, state:str) -> str:
        text = {
            "key": device_key,
            "Status": state
        }
        return json.dumps(text)


    def client_on_connect(self):
        client = self.client

        # Mqtt client is on connect
        def on_connect(client, userdata, flags, rc, properties) -> None:
            if rc == 0:
                client.publish(self.device_key + "/Status", Mqtt_Connect.create_state(self.device_key, "online"), qos=1, retain=True)
                print("Connected to MQTT Broker")
                client.publish(self.device_key + '/Matching', json.dumps({ 'key': self.device_key,
                                                                           'deviceTypeID': self.device_id,
                                                                           'deviceVersion': self.device_version,
                                                                           'ipCamera': self.ip_camera }))
                print('Mathced')
                for subscribe_topic in self.subscribe_topics:
                    client.subscribe(self.device_key + subscribe_topic)
                print('Subscribed')
            else:
                print(f"Failed to connect, return code {rc}\n")

        
        client.on_connect = on_connect
        time.sleep(5)
        Mqtt_Connect.set_current_setting(self)
     

    # Mqtt client did not connect
    def on_disconnect(self, client, userdata, rc) -> None:
        print("Disconnected from MQTT Broker")

    # Send the device id
    def client_matching_device(self) -> None:

        text = {
            'key': self.device_key,
            'deviceTypeID': self.device_id,
            'deviceVersion': self.device_version,
            'ipCamera': self.ip_camera
        }
        self.client.publish(self.device_key + '/Matching', json.dumps(text))

    # On message callback function
    def on_message(self, client, userdata, message) -> None:
        print(message.payload.decode('utf-8'))

        # Turns playload message from string to dictionary
        data = json.loads(message.payload.decode('utf-8'))
        
        try:
            self.current_setting[data['sensorNO'] - 1]['sensorSelect'] = data['sensorSelect']
        except:
            print("set value already")
            
        if message.topic == self.device_key + self.subscribe_topics[0]:         # Change number of sensor
            if self.number_of_sensor_value > data['newSensorAmount']:
                self.current_setting.pop()
            elif self.number_of_sensor_value < data['newSensorAmount']:
                self.current_setting.append({"sensorNo":data['newSensorAmount'], "sensorSelect":0, "decimal":0})
                
            self.number_of_sensor_value = data['newSensorAmount']
        elif message.topic == self.device_key + self.subscribe_topics[1]:       # Change value decimal
            self.current_setting[data['sensorNO'] - 1]['decimal'] = data['decimal']
        elif message.topic == self.device_key + self.subscribe_topics[2]:       # Change calibrate value
            self.current_setting[data['sensorNO'] - 1]['sensorCalibrateValue'] = data['sensorCalibrateValue']
        elif message.topic == self.device_key + self.subscribe_topics[3]:       # Change sensor low limit
            self.current_setting[data['sensorNO'] - 1]['sensorValueLowLimit'] = data['valueSensorLowLimit']
        elif message.topic == self.device_key + self.subscribe_topics[4]:       # Change sensor high limit
            self.current_setting[data['sensorNO'] - 1]['sensorValueHighLimit'] = data['valueSensorHighLimit']
        elif message.topic == self.device_key + self.subscribe_topics[5]:       # Change sensor option
            self.current_setting[data['sensorNO'] - 1]['sensorOption'] = data['sensorOption']
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
        elif message.topic == self.device_key + self.subscribe_topics[8]:       # Change out of set point status
            self.out_of_set_point_notification_status = data['sensorOutOfSetPointStatus']

            if data['sensorOutOfSetPointStatus'] :
                self.out_of_set_point_notification_start_time = time.time()
            else:
                self.out_of_set_point_notification_start_time = 0
        elif message.topic == self.device_key + self.subscribe_topics[9]:       # Change out of set point
            self.out_of_set_point_notification_option = data['sensorOutOfSetPoint'] 

            if data['sensorOutOfSetPoint'] == 0:
                self.out_of_set_point_notification_start_time = 0
            else:
                self.out_of_set_point_notification_start_time = time.time()
        elif message.topic == self.device_key + self.subscribe_topics[10]:      # Manual capture
            if "key" in data:
                self.is_capture = True
        elif message.topic == self.device_key + self.subscribe_topics[11]:      # Change notification method for each value
            self.current_setting[data['sensorNo'] - 1]['notifyMethod'] = data['notifyMethod']
        elif message.topic == self.device_key + self.subscribe_topics[12]:      # Change notification option for each value
            self.current_setting[data['sensorNo'] - 1]['notifyInterval'] = data['notifyInterval']
        elif message.topic == self.device_key + self.subscribe_topics[13]:      # Change line token
            self.line_token = data["lineToken"]
        elif message.topic == self.device_key + self.subscribe_topics[14]:      # OTA
            self.update_ota()

    # Send message to mqtt
    def client_on_message(self, message:str) -> None:
        self.client.on_message = self.on_message

    # Send values to mqtt
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
            
        for i in range(self.number_of_sensor_value):
            # ตรงเงื่อนไขต้องมาเปลี่ยนแต่ตอนนี้เรากำหนด ขาเข้า เป็น 1 ขาออก 2
            if self.current_setting[i]['sensorSelect'] == 1:
                self.client.publish(self.device_key + '/ValueSensor', to_json(self.device_key, self.current_setting[i]['sensorNo'], self.current_setting[i]['sensorSelect'], valuesList[0]))
            elif self.current_setting[i]['sensorSelect'] == 2:
                self.client.publish(self.device_key + '/ValueSensor', to_json(self.device_key, self.current_setting[i]['sensorNo'], self.current_setting[i]['sensorSelect'], valuesList[1]))
            else:
                self.client.publish(self.device_key + '/ValueSensor', to_json(self.device_key, self.current_setting[i]['sensorNo'], self.current_setting[i]['sensorSelect'], 0))

    # Reconnect to the broker with updated parameters
    def reconnect(self) -> None:
        self.client.disconnect()
        self.client.connect(self.broker_address, self.port)
        self.client.subscribe(self.device_key)
        
    # update code via ota
    def update_ota(self,) -> None:
        ROOT = os.path.dirname(__file__)

        file_url = 'https://updatego.modela.co.th/testpi/download.zip'

        local_file = 'downloaded_file.zip'
                
        response = requests.get(file_url, stream=True)

        if response.status_code == 200:
                # Open the local file in binary write mode
                with open(local_file, 'wb') as file:
                    # Write the content of the response to the file
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                print(f"File downloaded successfully: {local_file}")
        else:
            print(f"Failed to download file. Status code: {response.status_code}")

        if local_file.endswith('.zip'):
            with zipfile.ZipFile(local_file, 'r') as zip_ref:
                # Extract all the contents to the specified folder
                zip_ref.extractall(ROOT)
                print(f"File extracted successfully to: {ROOT}")
            os.remove('downloaded_file.zip')
            print("[INFO] The device will reboot in 6 seconds . . . !")
            time.sleep(6)
            os.system('sudo reboot')

    
        else:
            print("[WARNING] The downloaded file is not a ZIP file. No extraction performed.")
            
            
    # All of line notification
    def line_notification(self, image, valuesList:list):
        
        # Did user send the line token?
        if self.line_token != "":
                cv2.imwrite('notice.jpg', image)
                while len(valuesList) < self.number_of_sensor_value and self.number_of_sensor_value > 0:
                    try:
                        valuesList.append(0)
                    except Exception as e:
                        continue

                # valuesList = [value/(10**self.current_setting[i]['decimal']) for i, value in enumerate(valuesList) if i < self.number_of_sensor_value]
                
                notify_url = 'https://notify-api.line.me/api/notify'            # Line notification URL
                LINE_HEADERS = {'Authorization':'Bearer ' + self.line_token}    # Line notification header
                
                # Get the notification state for each sensor option
                def low_high_notification(option:int, actual_value:float, value_low_limit:float, value_high_limit:float) -> str:
                    
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
                                return 'The value is lower than low limit: OFF'
                            elif actual_value > value_high_limit:
                                return 'The value is higher than high limit: ON'
                        case 2:    
                            if actual_value < value_low_limit:
                                return 'The value is lower than low limit: ON'
                            elif actual_value > value_high_limit:
                                return 'The value is higher than high limit: OFF'
                        case 3:
                            if actual_value > value_high_limit:
                                return 'The value is higher than high limit: ON'
                        case 4:
                            if actual_value < value_low_limit:
                                return 'The value is lower than low limit: OFF'
                        case 5:
                            if actual_value < value_low_limit:
                                return 'The value is lower than low limit: ON'
                        case 6:
                            if actual_value > value_high_limit:
                                return 'The value is higher than high limit: OFF'
                        case _:
                            return ""

                # Notification for each value
                for value_sensor in self.current_setting:
                    try:
                        if value_sensor['notificationStartTime'] > 0:
                            if value_sensor['notifyInterval'] == 1:
                                notification_state = low_high_notification(value_sensor['sensorOption'], valuesList[value_sensor['sensorNo'] - 1], value_sensor['sensorValueLowLimit'], value_sensor['sensorValueHighLimit'])
                            else:
                                if time.time() - value_sensor['notificationStartTime'] >= self.value_notification_options[str(value_sensor['notifyInterval'])]:
                                    notification_state = low_high_notification(value_sensor['sensorOption'], valuesList[value_sensor['sensorNo'] - 1], value_sensor['sensorValueLowLimit'], value_sensor['sensorValueHighLimit'])
                                    if notification_state != "": 
                                        value_sensor['notificationStartTime'] = time.time()

                        if notification_state != "":
                            session_post = requests.post(notify_url, headers=LINE_HEADERS, data= {'message': notification_state})
            
                    except Exception as e:
                        continue

                if self.is_capture:
                    print("capture to line!")
                    session_post = requests.post(notify_url, headers=LINE_HEADERS, files={'imageFile': ('notice.jpg', open('notice.jpg', 'rb'), 'image/jpeg')}, data= {'message': 'Capture!'})
                    self.is_capture = False
            
                if self.period_notification_status and self.period_notification_option != 0:
                    if time.time() - self.peroid_notification_start_time >= float(self.period_time_options[str(self.period_notification_option)]):
                        session_post = requests.post(notify_url, headers=LINE_HEADERS, files={'imageFile': ('notice.jpg', open('notice.jpg', 'rb'), 'image/jpeg')}, data= {'message': 'Period notification'})
                        self.peroid_notification_start_time = time.time()
                
                if self.out_of_set_point_notification_status and self.out_of_set_point_notification_option != 0:
                    if time.time() - self.out_of_set_point_notification_start_time >= self.out_of_set_point_options[str(self.out_of_set_point_notification_option)]:

                        for value_sensor in self.current_setting:
                            if time.time() - value_sensor['notificationStartTime'] >= self.value_notification_options[str(value_sensor['notifyInterval'])]:
                                    notification_state = low_high_notification(value_sensor['sensorOption'], valuesList[value_sensor['sensorNo'] - 1], value_sensor['sensorValueLowLimit'], value_sensor['sensorValueHighLimit'])
                                    if notification_state != "": 
                                        session_post = requests.post(notify_url, headers=LINE_HEADERS, files={'imageFile': ('notice.jpg', open('notice.jpg', 'rb'), 'image/jpeg')}, data= {'message': 'Out of set point notification'})
                                        self.out_of_set_point_notification_start_time = time.time()
                                        break
        else:
            print("no line token")
        