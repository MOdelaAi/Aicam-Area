from gpiozero import RGBLED, Button, LED
import time
import os
import subprocess
import re
# Nofication through RGB LED
class LED_Notification:
    # Class construction
    def __init__(self, red_pin:int, green_pin:int, blue_pin:int) -> None:
        self.rgb_led = RGBLED(red = red_pin, green = green_pin, blue = blue_pin, active_high = True)
        self.red = (1, 0.007, 0.005)
        self.green = (0.8, 1, 0)
        self.blue = (0, 1, 1)
        self.yellow = (1, 0.5, 0)
        
    # Set new color code for red LED
    def set_red(self, RED:float, GREEN:float, BLUE:float) -> None:
        self.red = (RED, GREEN, BLUE)

    # Get the current color code of red LED
    def get_red(self) -> tuple:
        return self.red

    # Set new color code for green LED
    def set_green(self, RED:float, GREEN:float, BLUE:float) -> None:
        self.green = (RED, GREEN, BLUE)

    # Get the current color code of green LED
    def get_green(self) -> tuple:
        return self.green
    
    # Set new color code for blue LED
    def set_blue(self, RED:float, GREEN:float, BLUE:float) -> None:
        self.blue = (RED, GREEN, BLUE)
    
    # Get the current color code of blue LED
    def get_blue(self) -> tuple:
        return self.blue
        
    # Set new color code for yellow LED
    def set_yellow(self, RED:float, GREEN:float, BLUE:float) -> None:
        self.yellow = (RED, GREEN, BLUE)
    
    # Get the current color code of yellow LED
    def get_yellow(self) -> tuple:
        return self.yellow
    
    # Turn the LED on in white
    def turn_on(self) -> None:
        self.rgb_led.on()

    # Turn the LED off
    def turn_off(self) -> None:
        self.rgb_led.off()

    # If the wifi is connected
    def wifi_and_server_connected(self) -> None:
        self.rgb_led.color = (1,0,0)
    
    # If the wifi is connecting or not connected
    def wifi_and_server_not_connected(self) -> None:
        self.rgb_led.blink(
            on_time = 0.1, 
            off_time = 0.1, 
            fade_in_time = 0, 
            fade_out_time = 0,
            on_color = (1,0,0),
            off_color = (0, 0, 0),
            n = None,
            background = True
            )
        
    # If the SD card has been registered
    def registered_SD_card(self) -> None:
        self.rgb_led.off()
    
    # If the SD card is not correct or has not been registered
    def unregistered_SD_card(self) -> None:
        self.rgb_led.blink(
            on_time = 0.1, 
            off_time = 0.1, 
            fade_in_time = 0, 
            fade_out_time = 0,
            on_color = (0,1,0),
            off_color = (1,0,1),
            n = None,
            background = True
            )

    # The device is processing
    def not_found_target(self) -> None:
        self.rgb_led.off()

    # If the object has been detected
    def detected_target(self) -> None:
        self.rgb_led.blink(
            on_time = 0.1, 
            off_time = 0.1, 
            fade_in_time = 0, 
            fade_out_time = 0,
            on_color = (0,1,0),
            off_color = (0, 0, 0),
            n = None,
            background = True
            )
        
class outload_Relay():
    outload = LED(27)
        
    def detected_selected()->None:
        outload_Relay.outload.on()

    def not_detected_selected()->None:
        outload_Relay.outload.off()

# All button action
class Button_Action:
    # Class constructor
    def __init__(self, btn_pin:int) -> None:
        self.btn = Button(btn_pin)
        self.press_time = 0
        self.hold_duration = 10
        self.held_duration = 0
        
        self.double_press_interval = 0.5
        self.last_press_time = 0
        self.press_count = 0
    
    # Set press_time
    def set_press_time(self, new_press_time:int) -> None:
        self.press_time = new_press_time

    # Get the current press_time
    def get_press_time(self) -> float|None:
        return self.press_time

    # Set holding time
    def set_hold_duration(self, new_hold_duration:int|None) -> None:
        self.hold_duration = new_hold_duration

    # Get current holding time
    def get_hold_duration(self) -> int|None:
        return self.hold_duration

    # Set current held time
    def set_held_duration(self, new_held_duration:int|None) -> None:
        self.held_duration = new_held_duration
    
    # Get current held time
    def get_held_duration(self) -> int|None:
        return self.held_duration

    # The button has been pressed for 4 seconds
    def reset_mode(self) -> bool:
             
        def button_pressed_action():
            self.press_time = time.time()

        def button_released_action():
            self.held_duration = time.time() - self.press_time
            if self.held_duration > self.hold_duration:
                
                file_remove = ['notice.jpg','wifi_config.bin','key_config.bin']
                for i in file_remove:
                    if os.path.isfile(i):
                        os.remove(i)
                    
                target = os.popen("nmcli -t -f TYPE,UUID,NAME con").read()

                # Regular expression to find the UUID
                pattern = r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"

                # Search for the UUID in the string
                match = re.search(pattern, target)
                # If a match is found, print the UUID
                if match:
                    uuid = match.group(0)
                    # os.system(f"sudo nmcli c delete {uuid}")
                    
                print('[INFO] The device is reseted now!')
                time.sleep(3)
                os.system("sudo reboot")
            self.held_duration = 0
            self.press_time = 0
        
        self.btn.when_pressed = button_pressed_action
        self.btn.when_released = button_released_action

        try:
            while True:
                time.sleep(1)
        except Exception as e:
            print(f"The error is '{e}'.")

    
if __name__ == '__main__':
    '''In this if we used dedug only.'''
    pass