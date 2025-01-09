from mq_connector import get_serial
import yaml
# Get the ip for registration and encoding to binary
registered_ip = get_serial().encode('ascii')

data = {
    'Device':{
        'type': '6003',
        'version': '1.0.0',
        'key_device': registered_ip.decode('utf-8'),
        'key_from_server': None,
        'wifi':{
            'status': False,
            'SSID': None,
            'password': None
            }
        },
    'Unlock-Device':['a7a52ebace42e4b0',]
}

# เขียนข้อมูลลงไฟล์ YAML
with open('config.yaml', 'w') as file:
    yaml.dump(data, file, default_flow_style=False, sort_keys=False)
