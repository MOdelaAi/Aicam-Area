import yaml
from devicecare import DeviceCare

def register_device():
    # Get the ip for registration and encoding to binary
    registered_ip = DeviceCare.get_serial().encode('ascii')

    data = {
        'Device':{
            'type': '6004',
            'version': '1.0.0',
            'key_device': registered_ip.decode('utf-8'),
            'key_from_server': None,
            'wifi':{
                'status': False,
                'SSID': None,
                'password': None
                },
            'OTAstatus': None
            },
        'Unlock-Device':['a7a52ebace42e4b0','776378273a99abf2']
    }

    # เขียนข้อมูลลงไฟล์ YAML
    with open('config.yaml', 'w') as file:
        yaml.dump(data, file, default_flow_style=False, sort_keys=False)

if __name__ =='__main__':
    register_device()