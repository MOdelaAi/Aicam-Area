from mq_connector import get_serial

# Get the ip for registration and encoding to binary
registered_ip = get_serial().encode('ascii')

# Creates regist.bin as binary file
with open("regist.bin", "wb") as file:
    file.write(registered_ip)
    file.close()
