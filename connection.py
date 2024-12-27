import sys
import os
import logging
import asyncio
import threading
from typing import Any, Dict, Union

from bless import (  # type: ignore
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions,
)

logger = logging.getLogger(name=__name__)

trigger: Union[asyncio.Event, threading.Event]
if sys.platform in ["darwin", "win32"]:
    trigger = threading.Event()
else:
    trigger = asyncio.Event()


def read_request(characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
    logger.debug(f"Reading {characteristic.value}")
    return characteristic.value


def write_request(characteristic: BlessGATTCharacteristic, value: Any, **kwargs):
    characteristic.value = value
    logger.debug(f"Char value set to {characteristic.value}")
    if characteristic.value is not None:
        value = bytearray(value).decode().split(",")
        ssid = value[0][5:]
        wifi_password = value[1][9:]
        check_list_wifi = os.popen("sudo iwlist wlan0 scan | grep SSID").read()
        if ssid in check_list_wifi:
            key_config = value[2][4:].encode('ascii')
            if len(wifi_password) != 0:
                status = os.popen(f'sudo nmcli dev wifi connect "{value[0][5:]}" password "{value[1][9:]}"').read()
                wifi_config = f"sudo nmcli dev wifi connect \"{value[0][5:]}\" password \"{value[1][9:]}\"".encode('ascii')
            else:
                status = os.popen(f'sudo nmcli dev wifi connect "{value[0][5:]}"').read()
                wifi_config = f"sudo nmcli dev wifi connect \"{value[0][5:]}\"".encode('ascii')
                
            if 'successfully' in status:
                with open("wifi_config.bin", "wb") as file:
                    file.write(wifi_config)

                with open("key_config.bin", "wb") as file:
                    file.write(key_config)

                logger.debug("write file now")
                trigger.set()
                os._exit(1)


async def run(loop):
    trigger.clear()

    # Instantiate the server
    gatt: Dict = {
        "A07498CA-AD5B-474E-940D-16F1FBE7E8CD": {
            "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B": {
                "Properties": (
                    GATTCharacteristicProperties.read
                    | GATTCharacteristicProperties.write
                    | GATTCharacteristicProperties.indicate
                ),
                "Permissions": (
                    GATTAttributePermissions.readable
                    | GATTAttributePermissions.writeable
                ),
                "Value": None,
            }
        },
        "5c339364-c7be-4f23-b666-a8ff73a6a86a": {
            "bfc0c92f-317d-4ba9-976b-cc11ce77b4ca": {
                "Properties": GATTCharacteristicProperties.read,
                "Permissions": GATTAttributePermissions.readable,
                "Value": bytearray(b"\x69"),
            }
        },
    }
    my_service_name = "AI counter device 🤖" # NAME OF BLE DEVICE
    server = BlessServer(name=my_service_name, loop=loop)
    server.read_request_func = read_request
    server.write_request_func = write_request

    await server.add_gatt(gatt)
    await server.start()
    logger.debug(server.get_characteristic("51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B"))
    logger.debug("Advertising")
    logger.info(
        "Write '0xF' to the advertised characteristic: "
        + "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B"
    )
    if trigger.__module__ == "threading":
        trigger.wait()
    else:
        await trigger.wait()
    await asyncio.sleep(2)
    logger.debug("Updating")
    server.get_characteristic("51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B").value = bytearray(
        b"i"
    )
    server.update_value(
        "A07498CA-AD5B-474E-940D-16F1FBE7E8CD", "51FF12BB-3ED8-46E5-B4F9-D64E2FEC021B"
    )
    await asyncio.sleep(5)
    await server.stop()

def run_ble_server():
    print("BLE server is starting")
    loop = asyncio.new_event_loop() 
    asyncio.set_event_loop(loop)    
    loop.run_until_complete(run(loop))
    
def run_camera():
    import cv2
    import re
    from pyzbar.pyzbar import decode
    print("qrcode reader is starting")
    # Open the webcam
    cap = cv2.VideoCapture(0)
    while True:
        # Capture frame-by-frame
            
        ret, frame = cap.read()
        if not ret:
            break

        # Decode QR codes in the frame
        decoded_objects = decode(frame)
        # print(decoded_objects)
        for obj in decoded_objects:
            
            data = obj.data.decode('utf-8')
            print(f"QR Code Data: {data}",type(data))
            ssid_match = re.search(r"SSID:([^,]+)", data)
            password_match = re.search(r"Password:([^,]+)", data)
            key_match = re.search(r"Key:([^,]+)", data)

            # เก็บข้อมูลที่ดึงได้
            ssid = ssid_match.group(1) if ssid_match else None
            password = password_match.group(1) if password_match else None
            key = key_match.group(1) if key_match else None
            # print(ssid,password,key,type(ssid),type(password),type(key))
            check_list_wifi = os.popen("sudo iwlist wlan0 scan | grep SSID").read()
            if ssid in check_list_wifi:
                key_config = key
                if len(password) != 0:
                    status = os.popen(f'sudo nmcli dev wifi connect "{ssid}" password "{password}"').read()
                    wifi_config = f"sudo nmcli dev wifi connect \"{ssid}\" password \"{password}\"".encode('ascii')
                else:
                    status = os.popen(f'sudo nmcli dev wifi connect "{ssid}"').read()
                    wifi_config = f"sudo nmcli dev wifi connect \"{ssid}\"".encode('ascii')
                if 'successfully' in status:
                    print("write file now")
                    with open("wifi_config.bin", "wb") as file:
                        file.write(wifi_config)

                    with open("key_config.bin", "wb") as file:
                        file.write(key_config.encode('ascii'))
                    os._exit(1)
                print("wifi or password is not correct")
                continue

def main():
    # สร้าง Thread สำหรับรัน BLE Server
    ble_thread = threading.Thread(target=run_ble_server)
    # สร้าง Thread สำหรับรัน Camera
    camera_thread = threading.Thread(target=run_camera)

    # เริ่มการทำงานของ Threads
    ble_thread.start()
    camera_thread.start()

    # รอให้ Threads ทำงานเสร็จ
    ble_thread.join()
    camera_thread.join()

if __name__ == "__main__":
    main()