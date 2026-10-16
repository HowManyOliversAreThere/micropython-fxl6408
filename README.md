# FXL6408 GPIO expander

A MicroPython driver for the onsemi (formerly Fairchild) **FXL6408**, an
8-bit I2C GPIO expander. Every pin can be an input or a push-pull output,
with optional pull-up or pull-down resistors and per-pin interrupts on the
chip's open-drain `INT` output.

Copy `fxl6408.py` onto your board, or install it with `mip`:

```python
import mip
mip.install("github:HowManyOliversAreThere/micropython-fxl6408")
```

## Usage

```python
from machine import I2C, Pin
import fxl6408

i2c = I2C(0, sda=Pin(19), scl=Pin(20), freq=400_000)
io = fxl6408.FXL6408(i2c, address=fxl6408.ADDR_LOW)   # 0x43, ADDR pin low

io.setup(0, fxl6408.OUT, value=1)                  # P0: output, high
io.setup(1, fxl6408.IN, pull=fxl6408.PULL_UP)      # P1: input with pull-up
io.write(0, 0)
print(io.read(1))

led = io.pin(2, fxl6408.OUT)                       # machine.Pin-style handle
led.toggle()

io.enable_interrupt(1)          # INT asserts when P1 changes from its level now
flags = io.read_interrupts()    # bitmask of pins that triggered; reading clears INT
```

See [examples/buttons_and_led.py](examples/buttons_and_led.py) for a fuller
example that uses the `INT` pin.

## Notes

- The I2C address is `0x43` with the `ADDR` pin low and `0x44` with it high
  (`ADDR_LOW` / `ADDR_HIGH`).
- By default the constructor checks the manufacturer ID bits and then does a
  software reset, which puts every pin back to an input with its pull-down
  on. Pass `reset=False` to keep the chip's current state, for example after
  a microcontroller reset where outputs should not glitch.
- If the chip's active-low `RESET` pin is wired to a GPIO, pass it as
  `reset_pin` to pulse it at start-up.
- The chip has no real open-drain output mode. `OPEN_DRAIN` is emulated by
  switching a pin between driving low and high-impedance.
- The driver keeps shadow copies of the configuration registers, so
  changing one pin never disturbs the others. If something else on the bus
  also writes to the chip, construct the driver with `reset=False` to sync
  from the device.

## License

MIT - see [LICENSE](LICENSE).
