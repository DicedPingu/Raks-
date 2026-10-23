"""Direct /dev/uinput access (ctypes-free: just fcntl + struct) and virtual devices.

Provides:
  * pack_event / pack_user_dev  - kernel structure packing (unit tested)
  * diff_events                 - PadState -> list of (type, code, value)
  * Gamepad / Mouse / Keyboard  - real (uinput) or mock (log only) devices
"""
import fcntl
import logging
import os
import struct
import time

from protocol import BUTTONS, BUTTON_BIT, PadState

log = logging.getLogger("raks.uinput")

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0x00, 0x01, 0x02, 0x03
SYN_REPORT = 0

BTN_CODES = {
    "south": 0x130, "east": 0x131, "north": 0x133, "west": 0x134,
    "tl": 0x136, "tr": 0x137, "tl2": 0x138, "tr2": 0x139,
    "select": 0x13A, "start": 0x13B, "mode": 0x13C,
    "thumbl": 0x13D, "thumbr": 0x13E,
}
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11
REL_X, REL_Y, REL_WHEEL = 0x00, 0x01, 0x08
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
KEY_LEFTSHIFT = 42

# ioctl numbers (linux/uinput.h)
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567

ABS_CNT = 64
EVENT_FMT = "llHHi"  # struct input_event (native sizes)
EVENT_SIZE = struct.calcsize(EVENT_FMT)
USER_DEV_FMT = "<80sHHHHI"
USER_DEV_SIZE = struct.calcsize(USER_DEV_FMT) + 4 * ABS_CNT * 4

# (min, max, fuzz, flat) - Xbox-360-like ranges
GAMEPAD_ABS = {
    ABS_X: (-32768, 32767, 16, 128), ABS_Y: (-32768, 32767, 16, 128),
    ABS_RX: (-32768, 32767, 16, 128), ABS_RY: (-32768, 32767, 16, 128),
    ABS_Z: (0, 255, 0, 0), ABS_RZ: (0, 255, 0, 0),
    ABS_HAT0X: (-1, 1, 0, 0), ABS_HAT0Y: (-1, 1, 0, 0),
}


class UInputError(Exception):
    pass


def pack_event(etype, code, value, sec=0, usec=0) -> bytes:
    return struct.pack(EVENT_FMT, sec, usec, etype, code, value)


def pack_user_dev(name, bustype, vendor, product, version, abs_info=None, ff_effects_max=0) -> bytes:
    """Build the legacy `struct uinput_user_dev` blob written before UI_DEV_CREATE."""
    head = struct.pack(USER_DEV_FMT, name.encode()[:79], bustype, vendor, product, version, ff_effects_max)
    amax, amin, afuzz, aflat = ([0] * ABS_CNT for _ in range(4))
    for code, (lo, hi, fuzz, flat) in (abs_info or {}).items():
        amin[code], amax[code], afuzz[code], aflat[code] = lo, hi, fuzz, flat
    body = b"".join(struct.pack("<%di" % ABS_CNT, *arr) for arr in (amax, amin, afuzz, aflat))
    return head + body


def effective_state(s: PadState) -> PadState:
    """Digital trigger buttons imply a full analog trigger if none is supplied."""
    lt, rt = s.lt, s.rt
    if s.pressed("tl2") and lt == 0:
        lt = 255
    if s.pressed("tr2") and rt == 0:
        rt = 255
    return s._replace(lt=lt, rt=rt) if (lt, rt) != (s.lt, s.rt) else s


def diff_events(prev: PadState, new: PadState):
    """Return the list of (type, code, value) needed to go from prev to new."""
    prev, new = effective_state(prev), effective_state(new)
    ev = []
    changed = prev.buttons ^ new.buttons
    if changed:
        for name in BUTTONS:
            bit = BUTTON_BIT[name]
            if changed >> bit & 1:
                ev.append((EV_KEY, BTN_CODES[name], new.buttons >> bit & 1))
    for field, code in (("lx", ABS_X), ("ly", ABS_Y), ("rx", ABS_RX), ("ry", ABS_RY),
                        ("lt", ABS_Z), ("rt", ABS_RZ), ("hx", ABS_HAT0X), ("hy", ABS_HAT0Y)):
        a, b = getattr(prev, field), getattr(new, field)
        if a != b:
            ev.append((EV_ABS, code, b))
    return ev


class UInputDevice:
    """A raw uinput device; use .close() to destroy it."""

    def __init__(self, name, vendor, product, version=0x0110, bustype=0x03,
                 keys=(), rels=(), abs_info=None, path="/dev/uinput"):
        self.name = name
        self.fd = None
        self.path = path
        fd = None
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            if keys:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
                for k in keys:
                    fcntl.ioctl(fd, UI_SET_KEYBIT, k)
            if rels:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
                for r in rels:
                    fcntl.ioctl(fd, UI_SET_RELBIT, r)
            if abs_info:
                fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
                for a in abs_info:
                    fcntl.ioctl(fd, UI_SET_ABSBIT, a)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            os.write(fd, pack_user_dev(name, bustype, vendor, product, version, abs_info))
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as e:
            if fd is not None:
                os.close(fd)
            raise UInputError("cannot create %r via %s: %s" % (name, path, e))
        self.fd = fd

    def write(self, events):
        if self.fd is None or not events:
            return
        data = b"".join(pack_event(t, c, v) for t, c, v in events) + pack_event(EV_SYN, SYN_REPORT, 0)
        try:
            os.write(self.fd, data)
        except OSError as e:
            log.warning("write to %s failed: %s", self.name, e)

    def close(self):
        if self.fd is None:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = None


def uinput_available(path="/dev/uinput") -> bool:
    """True if we can open and use uinput (create+destroy a throwaway device)."""
    if not os.access(path, os.W_OK):
        return False
    try:
        UInputDevice("raks-probe", 0x1209, 0x0001, keys=[BTN_CODES["south"]], path=path).close()
        return True
    except UInputError:
        return False


class Gamepad:
    """Virtual gamepad. dev=None means mock mode (nothing is emitted)."""

    def __init__(self, name, vendor=0x045E, product=0x028E, mock=False, path="/dev/uinput"):
        self.name = name
        self.mock = mock
        self.dev = None
        if not mock:
            self.dev = UInputDevice(name, vendor, product, version=0x0110,
                                    keys=list(BTN_CODES.values()), abs_info=GAMEPAD_ABS, path=path)
        log.info("created %s pad %r", "mock" if mock else "uinput", name)

    def emit(self, events):
        if self.dev:
            self.dev.write(events)

    def close(self):
        if self.dev:
            self.dev.close()
            self.dev = None
        log.info("destroyed pad %r", self.name)


# ---------------------------------------------------------------- keyboard / mouse
def _build_keymap():
    plain, shifted = {}, {}
    rows = [("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)]
    for letters, base in rows:
        for i, ch in enumerate(letters):
            plain[ch] = base + i
            shifted[ch.upper()] = base + i
    for i, ch in enumerate("1234567890"):
        plain[ch] = 2 + i
    for ch, sh in zip("1234567890", "!@#$%^&*()"):
        shifted[sh] = plain[ch]
    for ch, sh, code in (("-", "_", 12), ("=", "+", 13), ("[", "{", 26), ("]", "}", 27),
                         (";", ":", 39), ("'", '"', 40), ("`", "~", 41), ("\\", "|", 43),
                         (",", "<", 51), (".", ">", 52), ("/", "?", 53)):
        plain[ch] = code
        shifted[sh] = code
    plain[" "] = 57
    plain["\n"] = 28
    plain["\t"] = 15
    return plain, shifted


KEYS_PLAIN, KEYS_SHIFTED = _build_keymap()
SPECIAL_KEYS = {
    "esc": 1, "backspace": 14, "tab": 15, "enter": 28, "space": 57,
    "up": 103, "left": 105, "right": 106, "down": 108, "home": 102, "end": 107,
    "pageup": 104, "pagedown": 109, "insert": 110, "delete": 111,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66,
    "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}
ALL_KEYS = sorted(set(KEYS_PLAIN.values()) | set(SPECIAL_KEYS.values()) | {KEY_LEFTSHIFT})


def text_to_key_events(text):
    """Translate text into a list of event batches (one batch per key tap)."""
    batches = []
    for ch in text:
        if ch in KEYS_PLAIN:
            code, shift = KEYS_PLAIN[ch], False
        elif ch in KEYS_SHIFTED:
            code, shift = KEYS_SHIFTED[ch], True
        else:
            continue
        b = []
        if shift:
            b.append((EV_KEY, KEY_LEFTSHIFT, 1))
        b += [(EV_KEY, code, 1), (EV_KEY, code, 0)]
        if shift:
            b.append((EV_KEY, KEY_LEFTSHIFT, 0))
        batches.append(b)
    return batches


class Keyboard:
    def __init__(self, mock=False, path="/dev/uinput"):
        self.mock = mock
        self.dev = None if mock else UInputDevice("Raks Keyboard", 0x1209, 0x7A01, version=1,
                                                  keys=ALL_KEYS, path=path)

    def type_text(self, text):
        log.info("keyboard type %r%s", text, " (mock)" if self.mock else "")
        for batch in text_to_key_events(text):
            if self.dev:
                self.dev.write(batch)

    def press(self, name):
        code = SPECIAL_KEYS.get(name)
        if code is None:
            return False
        log.info("keyboard key %s%s", name, " (mock)" if self.mock else "")
        if self.dev:
            self.dev.write([(EV_KEY, code, 1), (EV_KEY, code, 0)])
        return True

    def close(self):
        if self.dev:
            self.dev.close()


class Mouse:
    BUTTONS = (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE)

    def __init__(self, mock=False, path="/dev/uinput"):
        self.mock = mock
        self.buttons = 0
        self.dev = None if mock else UInputDevice(
            "Raks Mouse", 0x1209, 0x7A02, version=1, keys=list(self.BUTTONS),
            rels=[REL_X, REL_Y, REL_WHEEL], path=path)

    def move(self, dx, dy, wheel, buttons):
        ev = []
        if dx:
            ev.append((EV_REL, REL_X, dx))
        if dy:
            ev.append((EV_REL, REL_Y, dy))
        if wheel:
            ev.append((EV_REL, REL_WHEEL, wheel))
        changed = self.buttons ^ buttons
        for i, code in enumerate(self.BUTTONS):
            if changed >> i & 1:
                ev.append((EV_KEY, code, buttons >> i & 1))
        self.buttons = buttons
        if ev:
            log.debug("mouse %s%s", ev, " (mock)" if self.mock else "")
            if self.dev:
                self.dev.write(ev)

    def close(self):
        if self.dev:
            self.dev.close()
