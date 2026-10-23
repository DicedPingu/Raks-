"""Raks wire protocol: compact binary input frames + tiny JSON control messages.

See docs/PROTOCOL.md for the full description.
"""
import json
import struct
from typing import NamedTuple

PROTOCOL_VERSION = 1

# Button bit order inside the 16-bit button mask (bit 0 = first entry).
BUTTONS = ["south", "east", "north", "west", "tl", "tr", "tl2", "tr2",
           "select", "start", "mode", "thumbl", "thumbr"]
BUTTON_BIT = {name: i for i, name in enumerate(BUTTONS)}
BUTTON_MASK = (1 << len(BUTTONS)) - 1

# Codes a UI control may send (superset of BUTTONS, resolved client side).
CONTROL_CODES = BUTTONS + [
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "ls_up", "ls_down", "ls_left", "ls_right",
    "rs_up", "rs_down", "rs_left", "rs_right",
    "lt", "rt",
]

MSG_STATE = 0x01
MSG_MOUSE = 0x02

STATE_FMT = "<BHbbhhhhBB"
STATE_SIZE = struct.calcsize(STATE_FMT)  # 15
MOUSE_FMT = "<BhhbB"
MOUSE_SIZE = struct.calcsize(MOUSE_FMT)  # 7

MAX_JSON_BYTES = 4096


class ProtocolError(ValueError):
    pass


class PadState(NamedTuple):
    buttons: int = 0
    hx: int = 0      # D-pad horizontal -1/0/1
    hy: int = 0      # D-pad vertical   -1 (up) / 0 / 1 (down)
    lx: int = 0      # -32768..32767
    ly: int = 0
    rx: int = 0
    ry: int = 0
    lt: int = 0      # 0..255
    rt: int = 0

    def pressed(self, name):
        return bool(self.buttons >> BUTTON_BIT[name] & 1)


NEUTRAL = PadState()


class MouseMove(NamedTuple):
    dx: int
    dy: int
    wheel: int
    buttons: int  # bit0 left, bit1 right, bit2 middle


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def pack_state(s: PadState) -> bytes:
    return struct.pack(STATE_FMT, MSG_STATE, s.buttons & BUTTON_MASK,
                       _clamp(s.hx, -1, 1), _clamp(s.hy, -1, 1),
                       _clamp(s.lx, -32768, 32767), _clamp(s.ly, -32768, 32767),
                       _clamp(s.rx, -32768, 32767), _clamp(s.ry, -32768, 32767),
                       _clamp(s.lt, 0, 255), _clamp(s.rt, 0, 255))


def pack_mouse(m: MouseMove) -> bytes:
    return struct.pack(MOUSE_FMT, MSG_MOUSE, _clamp(m.dx, -32768, 32767),
                       _clamp(m.dy, -32768, 32767), _clamp(m.wheel, -128, 127),
                       m.buttons & 7)


def parse_binary(data: bytes):
    """Parse a binary frame. Returns ("state", PadState) or ("mouse", MouseMove)."""
    if not data:
        raise ProtocolError("empty frame")
    kind = data[0]
    if kind == MSG_STATE:
        if len(data) != STATE_SIZE:
            raise ProtocolError("bad state frame length %d" % len(data))
        _, btn, hx, hy, lx, ly, rx, ry, lt, rt = struct.unpack(STATE_FMT, data)
        return "state", PadState(btn & BUTTON_MASK, _clamp(hx, -1, 1), _clamp(hy, -1, 1),
                                 lx, ly, rx, ry, lt, rt)
    if kind == MSG_MOUSE:
        if len(data) != MOUSE_SIZE:
            raise ProtocolError("bad mouse frame length %d" % len(data))
        _, dx, dy, wheel, btn = struct.unpack(MOUSE_FMT, data)
        return "mouse", MouseMove(dx, dy, wheel, btn & 7)
    raise ProtocolError("unknown binary message type %d" % kind)


def parse_json(text) -> dict:
    """Parse a JSON control message; must be an object with a string "t"."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    if len(text) > MAX_JSON_BYTES:
        raise ProtocolError("message too large")
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise ProtocolError("invalid JSON: %s" % e)
    if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
        raise ProtocolError('message must be an object with a string "t"')
    return obj


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


def sanitize_name(name, default="", limit=24):
    if not isinstance(name, str):
        return default
    cleaned = "".join(ch for ch in name if ch.isprintable()).strip()[:limit]
    return cleaned or default
