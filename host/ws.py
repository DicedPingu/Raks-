"""Minimal RFC 6455 WebSocket server-side implementation (stdlib only)."""
import base64
import collections
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 8, 9, 10


class WSProtocolError(Exception):
    pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def handshake_response(key: str) -> bytes:
    return ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept_key(key)).encode()


def apply_mask(data: bytes, mask: bytes) -> bytes:
    n = len(data)
    if not n:
        return b""
    m = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big")


def encode_frame(opcode: int, payload: bytes = b"", fin: bool = True, mask: bytes = None) -> bytes:
    n = len(payload)
    head = bytearray([(0x80 if fin else 0) | opcode])
    mbit = 0x80 if mask else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 65536:
        head.append(mbit | 126)
        head += struct.pack("!H", n)
    else:
        head.append(mbit | 127)
        head += struct.pack("!Q", n)
    if mask:
        return bytes(head) + mask + apply_mask(payload, mask)
    return bytes(head) + payload


class FrameParser:
    """Incremental frame parser. feed() returns a list of (fin, opcode, payload)."""

    def __init__(self, max_payload=1 << 20, require_mask=True):
        self.buf = bytearray()
        self.max_payload = max_payload
        self.require_mask = require_mask

    def feed(self, data: bytes):
        self.buf += data
        frames = []
        while True:
            f = self._next()
            if f is None:
                return frames
            frames.append(f)

    def _next(self):
        buf = self.buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        fin = bool(b0 & 0x80)
        if b0 & 0x70:
            raise WSProtocolError("reserved bits set")
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        pos = 2
        if n == 126:
            if len(buf) < 4:
                return None
            n = struct.unpack("!H", bytes(buf[2:4]))[0]
            pos = 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n = struct.unpack("!Q", bytes(buf[2:10]))[0]
            pos = 10
        if opcode >= 8 and (not fin or n > 125):
            raise WSProtocolError("invalid control frame")
        if 3 <= opcode <= 7 or opcode > 10:
            raise WSProtocolError("unknown opcode %d" % opcode)
        if n > self.max_payload:
            raise WSProtocolError("frame too large")
        if self.require_mask and not masked:
            raise WSProtocolError("client frames must be masked")
        mask = b""
        if masked:
            if len(buf) < pos + 4:
                return None
            mask = bytes(buf[pos:pos + 4])
            pos += 4
        if len(buf) < pos + n:
            return None
        payload = bytes(buf[pos:pos + n])
        del buf[:pos + n]
        if masked:
            payload = apply_mask(payload, mask)
        return fin, opcode, payload


class Message:
    __slots__ = ("binary", "data")

    def __init__(self, binary, data):
        self.binary = binary
        self.data = data

    @property
    def text(self):
        return self.data.decode("utf-8", "replace")


class WebSocket:
    MAX_BUFFER = 1 << 20

    def __init__(self, reader, writer, max_payload=1 << 20):
        self.reader = reader
        self.writer = writer
        self.parser = FrameParser(max_payload)
        self.max_payload = max_payload
        self.closed = False
        self._queue = collections.deque()
        self._frag_op = None
        self._frag = bytearray()

    # ---- sending -------------------------------------------------------
    def _write(self, data: bytes):
        if self.closed:
            return
        try:
            if self.writer.transport.get_write_buffer_size() > self.MAX_BUFFER:
                self.abort()
                return
            self.writer.write(data)
        except Exception:
            self.abort()

    def send_text(self, text: str):
        self._write(encode_frame(OP_TEXT, text.encode()))

    def send_binary(self, data: bytes):
        self._write(encode_frame(OP_BIN, data))

    def close(self, code=1000, reason=""):
        if self.closed:
            return
        try:
            self.writer.write(encode_frame(OP_CLOSE, struct.pack("!H", code) + reason.encode()[:100]))
        except Exception:
            pass
        self.abort()

    def abort(self):
        self.closed = True
        try:
            self.writer.close()
        except Exception:
            pass

    # ---- receiving -----------------------------------------------------
    async def recv(self):
        """Return the next Message, or None when the connection is closed."""
        while not self._queue:
            if self.closed:
                return None
            try:
                data = await self.reader.read(65536)
            except (ConnectionError, OSError):
                data = b""
            if not data:
                self.closed = True
                return None
            try:
                frames = self.parser.feed(data)
            except WSProtocolError:
                self.close(1002, "protocol error")
                return None
            for fin, op, payload in frames:
                if not self._handle(fin, op, payload):
                    return None
        return self._queue.popleft()

    def _handle(self, fin, op, payload) -> bool:
        if op == OP_PING:
            self._write(encode_frame(OP_PONG, payload))
        elif op == OP_PONG:
            pass
        elif op == OP_CLOSE:
            self.close(1000)
            return False
        elif op == OP_CONT:
            if self._frag_op is None:
                self.close(1002, "unexpected continuation")
                return False
            self._frag += payload
            if len(self._frag) > self.max_payload:
                self.close(1009, "too big")
                return False
            if fin:
                self._queue.append(Message(self._frag_op == OP_BIN, bytes(self._frag)))
                self._frag_op, self._frag = None, bytearray()
        else:
            if self._frag_op is not None:
                self.close(1002, "expected continuation")
                return False
            if fin:
                self._queue.append(Message(op == OP_BIN, payload))
            else:
                self._frag_op, self._frag = op, bytearray(payload)
        return True
