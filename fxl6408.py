"""
MicroPython driver for the FXL6408UMX (onsemi / Fairchild)
8-bit I2C GPIO expander with configurable pull-up/down, interrupt, and
high-Z outputs.

I2C address (7-bit): 0x43 when the ADDR pin is low, 0x44 when it is high.

Quick start
-----------
    from machine import I2C, Pin as MPin
    from fxl6408 import FXL6408, IN, OUT, OPEN_DRAIN, PULL_UP

    i2c = I2C(0, scl=MPin(9), sda=MPin(8), freq=400_000)
    io = FXL6408(i2c)                      # address 0x43

    io.setup(0, OUT, value=1)              # P0 push-pull output, high
    io.setup(1, IN, pull=PULL_UP)          # P1 input with pull-up
    io.setup(2, OPEN_DRAIN, value=1)       # P2 open-drain (released)

    io.write(0, 0)
    print(io.read(1))

    # Pin-style wrapper (similar to machine.Pin)
    led = io.pin(0)
    led.toggle()

    # Interrupts (INT output pin of the chip is active-low, open-drain)
    io.enable_interrupt(1)                 # trigger when P1 != level at enable
    ...
    changed = io.read_interrupts()         # bitmask; reading clears the INT
"""

import time
from micropython import const

# ---- Public constants -------------------------------------------------------
# (Plain ints, not const(): the Pin class below re-exports them as class
# attributes, and MicroPython inlines const() names, which would turn
# "IN = IN" into the invalid "0 = 0".)
ADDR_LOW = 0x43    # ADDR pin = 0
ADDR_HIGH = 0x44   # ADDR pin = 1

# Pin modes
IN = 0
OUT = 1            # push-pull output
OPEN_DRAIN = 2     # emulated: drive low / release to high-Z

# Pull options (apply to inputs, and to outputs while in high-Z)
PULL_NONE = 0
PULL_UP = 1
PULL_DOWN = 2

# ---- Registers --------------------------------------------------------------
_REG_ID_CTRL = const(0x01)     # Device ID (bits 7:5 = 0b101) / SW reset (bit 0)
_REG_IO_DIR = const(0x03)      # 1 = output, 0 = input
_REG_OUT_STATE = const(0x05)   # output level
_REG_OUT_HIZ = const(0x07)     # 1 = output in high-Z (reset default: 0xFF)
_REG_IN_DEFAULT = const(0x09)  # default input state used for interrupt compare
_REG_PULL_EN = const(0x0B)     # 1 = pull resistor enabled (reset default: 0xFF)
_REG_PULL_SEL = const(0x0D)    # 1 = pull-up, 0 = pull-down
_REG_IN_STATUS = const(0x0F)   # input level (read-only)
_REG_INT_MASK = const(0x11)    # 1 = interrupt masked (reset default: 0x00)
_REG_INT_STATUS = const(0x13)  # interrupt flags (read-only, cleared on read)

_ID_MANUFACTURER = const(0b101)
_SW_RESET = const(0x01)


class FXL6408:
    def __init__(self, i2c, address=ADDR_LOW, reset=True, reset_pin=None,
                 check_id=True):
        """
        i2c        : machine.I2C (or SoftI2C) instance
        address    : 0x43 (ADDR low) or 0x44 (ADDR high)
        reset      : issue a software reset at init (all pins -> inputs)
        reset_pin  : optional machine.Pin wired to the chip's active-low RESET
        check_id   : verify the manufacturer ID bits on init
        """
        self._i2c = i2c
        self._addr = address

        if reset_pin is not None:
            reset_pin.init(reset_pin.OUT, value=0)
            time.sleep_ms(1)
            reset_pin.value(1)
            time.sleep_ms(1)

        if check_id:
            dev_id = self._read(_REG_ID_CTRL)
            if (dev_id >> 5) != _ID_MANUFACTURER:
                raise OSError("FXL6408 not found (ID reg = 0x%02X)" % dev_id)

        if reset:
            self.reset()
        else:
            self._sync()

    # ---- Low-level I2C ------------------------------------------------------
    def _read(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def _write(self, reg, value):
        self._i2c.writeto_mem(self._addr, reg, bytes((value & 0xFF,)))

    def _sync(self):
        """Load shadow copies from the device."""
        self._dir = self._read(_REG_IO_DIR)
        self._out = self._read(_REG_OUT_STATE)
        self._hiz = self._read(_REG_OUT_HIZ)
        self._in_default = self._read(_REG_IN_DEFAULT)
        self._pull_en = self._read(_REG_PULL_EN)
        self._pull_sel = self._read(_REG_PULL_SEL)
        self._int_mask = self._read(_REG_INT_MASK)
        # Open-drain bookkeeping is software only; unknown after a cold sync.
        self._od = 0

    @staticmethod
    def _mask(pin):
        if not 0 <= pin <= 7:
            raise ValueError("pin must be 0..7")
        return 1 << pin

    # ---- Device control -----------------------------------------------------
    def reset(self):
        """Software reset: all registers return to defaults (inputs, pulls on)."""
        self._write(_REG_ID_CTRL, _SW_RESET)
        time.sleep_ms(2)
        self._sync()

    @property
    def device_id(self):
        """Raw Device ID / Control register value."""
        return self._read(_REG_ID_CTRL)

    # ---- Pin configuration --------------------------------------------------
    def setup(self, pin, mode, pull=PULL_NONE, value=None):
        """
        Configure a single pin.

        mode  : IN, OUT (push-pull) or OPEN_DRAIN
        pull  : PULL_NONE / PULL_UP / PULL_DOWN
        value : initial level for outputs. If None, push-pull keeps its
                current output register bit; open-drain starts released.
        """
        m = self._mask(pin)

        # Pull resistors
        if pull == PULL_NONE:
            self._pull_en &= ~m
        else:
            if pull == PULL_UP:
                self._pull_sel |= m
            else:
                self._pull_sel &= ~m
            self._pull_en |= m
        self._write(_REG_PULL_SEL, self._pull_sel)
        self._write(_REG_PULL_EN, self._pull_en)

        if mode == IN:
            self._od &= ~m
            self._dir &= ~m
            self._write(_REG_IO_DIR, self._dir)
            return

        if mode == OPEN_DRAIN:
            self._od |= m
            self._out &= ~m                      # always drive 0 when enabled
            high = True if value is None else bool(value)
            if high:
                self._hiz |= m                   # released
            else:
                self._hiz &= ~m                  # actively low
        elif mode == OUT:
            self._od &= ~m
            if value is not None:
                if value:
                    self._out |= m
                else:
                    self._out &= ~m
            self._hiz &= ~m                      # drive the pin
        else:
            raise ValueError("invalid mode")

        # Order matters to avoid glitches: level, direction, then enable.
        self._write(_REG_OUT_STATE, self._out)
        self._dir |= m
        self._write(_REG_IO_DIR, self._dir)
        self._write(_REG_OUT_HIZ, self._hiz)

    # ---- Single-pin access --------------------------------------------------
    def read(self, pin):
        """Return the current logic level (0/1) seen on the pin."""
        m = self._mask(pin)
        return 1 if self._read(_REG_IN_STATUS) & m else 0

    def write(self, pin, value):
        m = self._mask(pin)
        self.write_port(m if value else 0, m)

    def toggle(self, pin):
        m = self._mask(pin)
        cur = (self._hiz if self._od & m else self._out) & m
        self.write_port(0 if cur else m, m)

    # ---- Port-wide access ---------------------------------------------------
    def read_port(self):
        """Return all 8 input levels as a byte."""
        return self._read(_REG_IN_STATUS)

    def write_port(self, value, mask=0xFF):
        """
        Write `value` to every output pin selected by `mask`. Pins that are
        inputs are unaffected on the wire, but their output register bits are
        updated so the level is ready when they become outputs.
        """
        mask &= 0xFF
        od = mask & self._od
        pp = mask & ~self._od & 0xFF
        if pp:
            self._out = (self._out & ~pp) | (value & pp)
            self._write(_REG_OUT_STATE, self._out)
        if od:
            # open-drain: 1 = release (high-Z), 0 = drive low
            self._hiz = (self._hiz & ~od) | (value & od)
            self._write(_REG_OUT_HIZ, self._hiz)

    @property
    def direction(self):
        """Direction register shadow (1 = output)."""
        return self._dir

    # ---- Interrupts ---------------------------------------------------------
    def enable_interrupt(self, pin, default=None):
        """
        Unmask the interrupt for `pin`. INT asserts (active low) whenever the
        input differs from its 'default' level.

        default : reference level (0/1). None = use the level present now,
                  so the interrupt fires on the next change from that level.
        """
        m = self._mask(pin)
        if default is None:
            default = self.read(pin)
        if default:
            self._in_default |= m
        else:
            self._in_default &= ~m
        self._int_mask &= ~m
        self._write(_REG_IN_DEFAULT, self._in_default)
        self._write(_REG_INT_MASK, self._int_mask)

    def disable_interrupt(self, pin):
        m = self._mask(pin)
        self._int_mask |= m
        self._write(_REG_INT_MASK, self._int_mask)

    def read_interrupts(self):
        """Return the interrupt-status bitmask. Reading clears the INT line."""
        return self._read(_REG_INT_STATUS)

    # ---- machine.Pin-like wrapper -------------------------------------------
    def pin(self, number, mode=None, pull=PULL_NONE, value=None):
        return Pin(self, number, mode, pull, value)


class Pin:
    """Lightweight machine.Pin-style handle for one FXL6408 pin."""

    IN = IN
    OUT = OUT
    OPEN_DRAIN = OPEN_DRAIN
    PULL_UP = PULL_UP
    PULL_DOWN = PULL_DOWN

    def __init__(self, expander, number, mode=None, pull=PULL_NONE, value=None):
        self._io = expander
        self._n = number
        expander._mask(number)  # validate
        if mode is not None:
            self.init(mode, pull, value)

    def init(self, mode, pull=PULL_NONE, value=None):
        self._io.setup(self._n, mode, pull, value)

    def value(self, v=None):
        if v is None:
            return self._io.read(self._n)
        self._io.write(self._n, v)

    __call__ = value

    def on(self):
        self._io.write(self._n, 1)

    def off(self):
        self._io.write(self._n, 0)

    def toggle(self):
        self._io.toggle(self._n)
