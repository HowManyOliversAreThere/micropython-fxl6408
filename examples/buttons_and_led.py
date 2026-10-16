"""
Read a button and drive an LED through an FXL6408, using its interrupt
output to notice changes.

Wiring for this example (change to suit):
    FXL6408 SDA/SCL  -> board I2C (pins below)
    FXL6408 INT      -> GPIO3, with a pull-up (INT is open-drain, active low)
    P0               -> LED (and resistor) to GND
    P1               -> push button to 3V3, with a pull-down
"""

import time
from machine import I2C, Pin

import fxl6408

i2c = I2C(0, sda=Pin(19), scl=Pin(20), freq=400_000)
io = fxl6408.FXL6408(i2c, address=fxl6408.ADDR_LOW)

led = io.pin(0, fxl6408.OUT, value=0)
io.setup(1, fxl6408.IN, pull=fxl6408.PULL_DOWN)
io.enable_interrupt(1, default=0)  # INT asserts while P1 differs from 0

changed = False


def on_int(_pin):
    global changed
    changed = True


int_pin = Pin(3, Pin.IN, Pin.PULL_UP)
int_pin.irq(trigger=Pin.IRQ_FALLING, handler=on_int)

print("Device ID register: 0x%02X" % io.device_id)
while True:
    if changed:
        changed = False
        flags = io.read_interrupts()  # clears INT
        pressed = io.read(1)
        print("interrupt flags 0b{:08b}, button {}".format(flags, "down" if pressed else "up"))
        led.value(pressed)
    time.sleep_ms(10)
