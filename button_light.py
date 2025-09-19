from gpiozero import RGBLED, Button, LED
import time
import functools
import yaml
import threading
from devicecare import DeviceCare
from logger_config import setup_logger
from device_register import register_device
#set logger
logger = setup_logger(__name__)
    
class outload_Relay():
    relays = {
        1: LED(27),
        2: LED(22)
        # เพิ่มได้อีก เช่น 3: LED(5)
    }

    @staticmethod
    def set_state(relay_no: int, state: bool) -> None:
        
        relay = outload_Relay.relays.get(relay_no)  

        if relay is not None:
            print(f"[GPIO] Relay {relay_no} {'ON' if state else 'OFF'}")
            relay.on() if state else relay.off()
        else:
            print(f"[WARNING] Relay {relay_no} not defined")
        
# All button action
class Button_Action:
    # Class constructor
    def __init__(self, btn_pin:int) -> None:
        self.btn = Button(btn_pin )
        self.press_time = 0
        self.hold_duration = 5
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

    # The button has been pressed for 6 seconds
    def reset_mode(self, state_light) -> bool:
    
        def button_pressed_action():
            self.press_time = time.time()

        def button_released_action(state_light):
            if self.press_time == 0:
                return 

        def button_released_action(state_light):
            self.held_duration = time.time() - self.press_time
            if self.held_duration > self.hold_duration:
                state_light.put(1)
                register_device()
                DeviceCare.del_log_files()
                logger.warning('setting from factory reset')
                DeviceCare.reboot_device()
            self.held_duration = 0
            self.press_time = 0
        
        self.btn.when_pressed = button_pressed_action
        self.btn.when_released = functools.partial(button_released_action, state_light)

        try:
            while True:
                time.sleep(1)
        except Exception as e:
            logger.error(f"The error is '{e}'.")

    
if __name__ == '__main__':
    pass
        



