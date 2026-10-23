import asyncio
import base64
import json
import os
import unittest

import _path  # noqa: F401
import config as config_mod
import protocol
import ws
from server import RaksServer


class Client:
    def __init__(self, port, path="/ws"):
        self.port, self.path = port, path
        self.parser = ws.FrameParser(require_mask=False)
        self.queue = []

    async def open(self):
        self.r, self.w = await asyncio.open_connection("127.0.0.1", self.port)
        key = base64.b64encode(os.urandom(16)).decode()
        self.w.write(("GET %s HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (self.path, key)).encode())
        head = await self.r.readuntil(b"\r\n\r\n")
        assert b"101" in head.split(b"\r\n")[0], head
        assert ws.accept_key(key).encode() in head
        return self

    def send(self, obj):
        if isinstance(obj, (bytes, bytearray)):
            self.w.write(ws.encode_frame(ws.OP_BIN, bytes(obj), mask=os.urandom(4)))
        else:
            self.w.write(ws.encode_frame(ws.OP_TEXT, json.dumps(obj).encode(), mask=os.urandom(4)))

    async def recv(self, timeout=3):
        while not self.queue:
            data = await asyncio.wait_for(self.r.read(4096), timeout)
            if not data:
                return None
            self.queue += self.parser.feed(data)
        fin, op, payload = self.queue.pop(0)
        return json.loads(payload) if op == ws.OP_TEXT else payload

    async def recv_type(self, t, timeout=3):
        while True:
            m = await self.recv(timeout)
            if m is None or (isinstance(m, dict) and m.get("t") == t):
                return m

    def close(self):
        self.w.close()


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cfg = config_mod.load_config(None)
        cfg.update(port=0, bind="127.0.0.1", max_players=2, pin="")
        self.cfg = cfg
        self.srv = RaksServer(cfg, _path.ROOT, mock=True)
        await self.srv.start()

    async def asyncTearDown(self):
        await self.srv.stop()

    async def test_player_flow(self):
        c = await Client(self.srv.port).open()
        c.send({"t": "hello", "id": "abc", "name": "Ann", "v": 1})
        w = await c.recv_type("welcome")
        self.assertEqual(w["slot"], 1)
        pad = self.srv.manager.players[1].device
        c.send(protocol.pack_state(protocol.PadState(buttons=1, lx=500)))
        await asyncio.sleep(0.2)
        self.assertEqual(self.srv.manager.players[1].state.lx, 500)
        c.send({"t": "ping", "ts": 5})
        p = await c.recv_type("pong")
        self.assertEqual(p["ts"], 5)
        c.close()
        await asyncio.sleep(0.2)
        # reconnect keeps slot
        c2 = await Client(self.srv.port).open()
        c2.send({"t": "hello", "id": "abc", "name": "Ann"})
        w2 = await c2.recv_type("welcome")
        self.assertEqual((w2["slot"], w2["resumed"]), (1, True))
        self.assertIsNotNone(pad)
        c2.close()

    async def test_full_and_bad_hello(self):
        cs = []
        for i in range(2):
            c = await Client(self.srv.port).open()
            c.send({"t": "hello", "id": "id%d" % i})
            await c.recv_type("welcome")
            cs.append(c)
        c = await Client(self.srv.port).open()
        c.send({"t": "hello", "id": "third"})
        e = await c.recv_type("error")
        self.assertEqual(e["code"], "full")
        for c in cs:
            c.close()

    async def test_pin(self):
        self.srv.pin = "1234"
        c = await Client(self.srv.port).open()
        c.send({"t": "hello", "id": "x", "pin": "0000"})
        e = await c.recv_type("error", timeout=5)
        self.assertEqual(e["code"], "pin")
        c = await Client(self.srv.port).open()
        c.send({"t": "hello", "id": "x", "pin": "1234"})
        self.assertEqual((await c.recv_type("welcome"))["slot"], 1)
        c.close()

    async def test_viewer_and_http(self):
        v = await Client(self.srv.port, "/ws/view").open()
        c = await Client(self.srv.port).open()
        c.send({"t": "hello", "id": "z"})
        await c.recv_type("welcome")
        c.send(protocol.pack_state(protocol.PadState(buttons=2)))
        snap = await v.recv_type("snap", timeout=3)
        self.assertIsNotNone(snap)
        r, w = await asyncio.open_connection("127.0.0.1", self.srv.port)
        w.write(b"GET /api/info HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        body = await r.read()
        self.assertIn(b"200", body.split(b"\r\n")[0])
        self.assertIn(b'"max_players"', body)
        r, w = await asyncio.open_connection("127.0.0.1", self.srv.port)
        w.write(b"GET /play/../config.json HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertNotIn(b" 200", (await r.read()).split(b"\r\n")[0])
        c.close()
        v.close()


if __name__ == "__main__":
    unittest.main()
