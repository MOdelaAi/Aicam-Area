import re
import subprocess
from urllib.parse import urlparse
import os
import glob
import time
import socket
import logging
import yaml
import requests
from logger_config import setup_logger
#set logger
logger = setup_logger(__name__)


ROOT = os.path.dirname(__file__)

class DeviceCare:
    
    def Map_value(inMin,inMax,outMin,outMax):
        try:
            iwconfig_result = os.popen('iwconfig wlan0').read()
            signal_level = int(re.search(r'Signal level=(-\d+)', iwconfig_result).group(1))
            result = (signal_level - inMin) * (outMax - outMin) / (inMax - inMin) + outMin
            if result > outMax:
                result = outMax
            elif result<outMin:
                result = outMin
            return round(result,2)
        except:
          return 0.0


    def get_cpu_temperature():
        result = subprocess.run(['vcgencmd', 'measure_temp'], stdout=subprocess.PIPE)
        
        output = result.stdout.decode('utf-8')
        
        temp = output.split('=')[1].split("'")[0]
        
        return float(temp)
    
    
    def Connection_wifi()->bool:
        try:
            with open("config.yaml", "r") as file:
                data = yaml.safe_load(file)

            info = data['Device']
            ssid = info['wifi']['SSID']
            password = info['wifi']['password']

            subprocess.run(['/usr/bin/sudo', 'nmcli', 'connection', 'delete', ssid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


            result = subprocess.run([
                '/usr/bin/sudo', 'nmcli', 'dev', 'wifi', 'connect', ssid, 'password', password
            ], capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"Connected to WiFi: {ssid}")
                return True
            else:
                logger.error(f"Failed to connect WiFi: {ssid} (code {result.returncode})")
                logger.error(f"stderr: {result.stderr.strip()}")
                return False

        except Exception as e:
            logger.exception(f"Exception while connecting to WiFi: {e}")
            return False
            
                
    def get_url()->str:
        if os.popen("hostname -I").read().strip() !='':
            url= f'http://{os.popen("hostname -I").read().strip()}'
            url_parts = url.split(" ")
            first_url = url_parts[0]
            parsed_url = urlparse(first_url)
            ip_camera = f"{parsed_url.scheme}://{parsed_url.hostname}:5000/video_feed" 
            logger.info(f"YOUR URL: {ip_camera}")
            return ip_camera
    
    def is_internet_connected(host="8.8.8.8", port=53, timeout=3):
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except socket.error as ex:
            return False
    
    def is_eth0_connected():
        try:
            result = subprocess.run(['cat', '/sys/class/net/eth0/carrier'], capture_output=True, text=True)
            return result.stdout.strip() == '1'
        except Exception as e:
            print(f"Error checking eth0: {e}")
        return False
        
        
    def is_wifi_connected():
        cmd = "nmcli -t -f active,ssid dev wifi | grep 'yes:'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode == 0  

    def check_cameras_connection():
        result = subprocess.run(['v4l2-ctl', '--list-devices'], stdout=subprocess.PIPE)
        output = result.stdout.decode('utf-8')
        devices = re.findall(r'(usb-xhci-hcd.*?):\s*(/dev/video\d+)', output)
        return [int(device[1].split('/')[-1].replace('video', '')) for device in devices if 'usb-xhci-hcd' in device[0]]
    
    def find_digit(text):
        match = re.search(r"\d+", text)
        if match:
            return int(match.group())
        else:
            return None
    
    def reboot_device():
        logger.warning("The device is reboot now!")
        time.sleep(7)
        os.system("sudo reboot")

    def get_serial() -> str|None:
        try:
            with open('/proc/cpuinfo', 'r') as f:               # Access cpuinfo
                for line in f:
                    if line.startswith('Serial'):               # Access the line starts with the word "Serial"
                        return line.strip().split(": ")[1]      # Get the vanished serial number
        except Exception as e:
            return None
    
    def get_mac_address(interface='wlan0'):
        try:
            result = subprocess.check_output(f"cat /sys/class/net/{interface}/address", shell=True)
            return result.decode('utf-8').strip()
        except subprocess.CalledProcessError:
            return None
    
    def del_log_files():
        # files_to_delete = glob.glob("*.log")
        # for file_path in files_to_delete:
        #     if os.path.exists(file_path):
        #         os.remove(file_path)
        if os.path.exists("app.log"):
            os.remove("app.log")
                
if __name__ == '__main__':
    # DeviceCare.Connection_wifi()
    # print(DeviceCare.is_eth0_connected())
    # print(DeviceCare.is_internet_connected())
    # print(DeviceCare.is_wifi_connected())
    # print(DeviceCare.Map_value(-105,-50,0,100))
    pass
