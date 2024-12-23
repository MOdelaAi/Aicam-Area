import re
import subprocess
from urllib.parse import urlparse
import os
import time
import socket
import logging


ROOT = os.path.dirname(__file__)
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s => %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

class DeviceCare:
    
    def Map_value(inMin,inMax,outMin,outMax):
        iwconfig_result = os.popen('iwconfig wlan0').read()
        signal_level = int(re.search(r'Signal level=(-\d+)', iwconfig_result).group(1))
        result = (signal_level - inMin) * (outMax - outMin) / (inMax - inMin) + outMin
        if result > outMax:
            result = outMax
        elif result<outMin:
            result = outMin
        return round(result,2)


    def get_cpu_temperature():
        result = subprocess.run(['vcgencmd', 'measure_temp'], stdout=subprocess.PIPE)
        
        output = result.stdout.decode('utf-8')
        
        temp = output.split('=')[1].split("'")[0]
        
        return float(temp)
    
    
    def wifi_connection_again()->bool:
        with open(f"{ROOT}/wifi_config.bin", "rb") as file:
            wifi_config = file.read().decode('ascii')
        start_index = wifi_config.find('connect "') + len('connect "')
        end_index = wifi_config.find('"', start_index)

        wifi_name = wifi_config[start_index:end_index]
        check_list_wifi = os.popen("sudo iwlist wlan0 scan | grep SSID").read()
        if wifi_name in check_list_wifi:
            status = os.popen(wifi_config).read()
            if 'successfully' in status:
                return True
             
        logging.warning("no wifi !")
        return False


    def check_internet(host="8.8.8.8", port=53, timeout=3)->bool:
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            
            return True
        except socket.error as ex:
            
            return False
        
                
    def get_url()->str:
        if os.popen("hostname -I").read().strip() !='':
            url= f'http://{os.popen("hostname -I").read().strip()}'
            url_parts = url.split(" ")
            first_url = url_parts[0]
            parsed_url = urlparse(first_url)
            ip_camera = f"{parsed_url.scheme}://{parsed_url.hostname}:5000/video_feed" 
            logging.info(f"YOUR URL: {ip_camera}")
            return ip_camera
    
    def reboot_device():
        logging.info("The device is reboot now!")
        time.sleep(7)
        os.system("sudo reboot")
    
    def check_wifi_and_internet_connection()->bool:
        try:
            # Run the `iwconfig` command to check for WiFi status
            result = subprocess.run(['iwconfig'], capture_output=True, text=True)
            internet_check = DeviceCare.check_internet()
            counter_reboot = 0 
            if 'ESSID:"' in result.stdout and internet_check:
                return True
            else:
                while True:
                    connection = DeviceCare.wifi_connection_again()
                    internet_check = DeviceCare.check_internet()
                    logging.debug(f"connection repeat again: \t connect wifi: ,{connection}, internet: {internet_check}")
                    if connection and internet_check:
                        break
                    if counter_reboot == 24:
                        DeviceCare.reboot_device()
                    counter_reboot +=1
                    time.sleep(5)
                return True
        
        except Exception as e:
            print(f"An error occurred: {e}")


if __name__ == '__main__':
    # DeviceCare.check_wifi_connection()
    pass
