"""HTTP + WebSocket server for Raks."""
import asyncio
import hmac
import json
import logging
import mimetypes
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import actions as actions_mod
import protocol
import qr
import ws as wsmod
from players import PlayerManager
from protocol import ProtocolError, sanitize_name
from uinput import Gamepad, Keyboard, Mouse, UInputError

log = logging.getLogger("raks.server")
VERSION = "0.1.0"
MOBILE_HINTS = ("android", "iphone", "ipad", "ipod", "mobile")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json",
        ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon"}


class RaksServer:
    def __init__(self, cfg, root, mock=False, ip="127.0.0.1"):
        self.cfg = cfg
        self.root = Path(root)
        self.mock = mock
        self.ip = ip
        self.port = cfg["port"]
        self.pin = cfg["pin"]
        self.actions = actions_mod.HostActions(cfg["actions"], dry_run=mock)
        self.manager = PlayerManager(cfg["max_players"], self._make_pad, cfg["slot_reserve_seconds"])
        self.viewers = set()
        self.keyboard = None
        self.mouse = None
        self.pin_fails = {}      # ip -> (count, locked_until)
        self.server = None
        self._tasks = []
        self.started = time.time()

    # ---- helpers ---------------------------------------------------------------
    @property
    def url(self):
        return "http://%s:%d/play/" % (self.ip, self.port)

    def _make_pad(self, name):
        u = self.cfg["uinput"]
        return Gamepad(name, u["vendor"], u["product"], mock=self.mock, path=u["path"])

    def info(self):
        return {"name": "Raks", "version": VERSION, "ip": self.ip, "port": self.port, "url": self.url,
                "mdns": "http://%s.local:%d/play/" % (self.cfg["hostname"], self.port),
                "mock": self.mock, "max_players": self.cfg["max_players"],
                "pin_required": bool(self.pin), "uptime": int(time.time() - self.started),
                "players": self.manager.roster()}

    def features(self):
        f = self.actions.features()
        f["keyboard"] = bool(self.cfg["actions"].get("keyboard"))
        f["mouse"] = bool(self.cfg["actions"].get("mouse"))
        f["admin"] = bool(self.cfg["allow_admin"])
        return f

    def _extra(self, kind):
        try:
            if kind == "keyboard":
                if self.keyboard is None:
                    self.keyboard = Keyboard(self.mock, self.cfg["uinput"]["path"])
                return self.keyboard
            if self.mouse is None:
                self.mouse = Mouse(self.mock, self.cfg["uinput"]["path"])
            return self.mouse
        except UInputError as e:
            log.warning("%s", e)
            return None

    # ---- lifecycle -------------------------------------------------------------
    async def start(self):
        self.server = await asyncio.start_server(self.handle, self.cfg["bind"], self.port, limit=16384)
        if self.port == 0:
            self.port = self.server.sockets[0].getsockname()[1]
        self._tasks.append(asyncio.create_task(self._broadcast_loop()))

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        if self.server:
            self.server.close()
        for v in list(self.viewers):
            v.abort()
        for p in list(self.manager.players.values()):
            if p.ws:
                p.ws.abort()
        self.manager.close_all()
        for dev in (self.keyboard, self.mouse):
            if dev:
                dev.close()

    async def _broadcast_loop(self):
        last = 0
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            if self.viewers and (self.manager.dirty or now - last > 2):
                self.manager.dirty = False
                msg = protocol.dumps(self.manager.snapshot())
                for v in list(self.viewers):
                    v.send_text(msg)
                last = now
            elif not self.viewers:
                self.manager.dirty = False

    def _broadcast_roster(self):
        self.manager.dirty = True
        msg = protocol.dumps({"t": "players", "players": self.manager.roster()})
        for p in self.manager.players.values():
            if p.ws and not p.bot:
                p.ws.send_text(msg)

    # ---- HTTP ------------------------------------------------------------------
    async def handle(self, reader, writer):
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        peer = (writer.get_extra_info("peername") or ("?", 0))[0]
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            url = urlsplit(target)
            if headers.get("upgrade", "").lower() == "websocket" and url.path in ("/ws", "/ws/view"):
                await self.handle_ws(reader, writer, headers, url.path, peer)
                return
            await self.handle_http(writer, method, url, headers)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, asyncio.LimitOverrunError,
                ConnectionError, ValueError, UnicodeError):
            pass
        except Exception:
            log.exception("request error")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    def _respond(writer, status, body=b"", ctype="text/plain; charset=utf-8", extra=None, head=False):
        reason = {200: "OK", 302: "Found", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}.get(status, "")
        hdr = ["HTTP/1.1 %d %s" % (status, reason), "Content-Type: " + ctype,
               "Content-Length: %d" % len(body), "Cache-Control: no-cache",
               "X-Content-Type-Options: nosniff", "Connection: close"]
        hdr += extra or []
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode() + (b"" if head else body))

    def _file(self, base, rel):
        base = base.resolve()
        p = (base / rel).resolve()
        if p != base and base not in p.parents:
            return None
        if p.is_dir():
            p = p / "index.html"
        return p if p.is_file() else None

    async def handle_http(self, writer, method, url, headers):
        head = method == "HEAD"
        if method not in ("GET", "HEAD"):
            return self._respond(writer, 405)
        path = url.path
        if path == "/":
            ua = headers.get("user-agent", "").lower()
            if "landing" not in url.query and any(h in ua for h in MOBILE_HINTS):
                return self._respond(writer, 302, extra=["Location: /play/"])
            return self._serve(writer, self.root / "host" / "web" / "landing.html", head)
        if path == "/debug":
            return self._serve(writer, self.root / "host" / "web" / "debug.html", head)
        if path == "/api/info":
            return self._respond(writer, 200, json.dumps(self.info()).encode(), "application/json", head=head)
        if path == "/qr.svg":
            svg = qr.to_svg(qr.make_qr(self.url)).encode()
            return self._respond(writer, 200, svg, "image/svg+xml", head=head)
        if path == "/play":
            return self._respond(writer, 302, extra=["Location: /play/"])
        for prefix, base in (("/play/", "client"), ("/presets/", "presets")):
            if path.startswith(prefix):
                f = self._file(self.root / base, path[len(prefix):])
                return self._serve(writer, f, head)
        self._respond(writer, 404, b"not found")

    def _serve(self, writer, f, head=False):
        if f is None or not f.is_file():
            return self._respond(writer, 404, b"not found")
        ctype = MIME.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        extra = ["Service-Worker-Allowed: /play/"] if f.name == "sw.js" else None
        self._respond(writer, 200, f.read_bytes(), ctype, extra, head)

    # ---- WebSocket ---------------------------------------------------------------
    async def handle_ws(self, reader, writer, headers, path, peer):
        key = headers.get("sec-websocket-key")
        if not key:
            return self._respond(writer, 400, b"bad websocket request")
        writer.write(wsmod.handshake_response(key))
        sock = wsmod.WebSocket(reader, writer)
        if path == "/ws/view":
            await self.run_viewer(sock)
        else:
            await self.run_player(sock, peer)

    async def run_viewer(self, sock):
        self.viewers.add(sock)
        sock.send_text(protocol.dumps(self.manager.snapshot()))
        try:
            while await sock.recv() is not None:
                pass
        finally:
            self.viewers.discard(sock)

    def _check_pin(self, peer, pin):
        if not self.pin:
            return True
        count, locked = self.pin_fails.get(peer, (0, 0))
        if locked > time.monotonic():
            return False
        if hmac.compare_digest(str(pin or ""), self.pin):
            self.pin_fails.pop(peer, None)
            return True
        count += 1
        self.pin_fails[peer] = (count, time.monotonic() + 30 if count >= 5 else 0)
        return False

    async def run_player(self, sock, peer):
        try:
            first = await asyncio.wait_for(sock.recv(), 8)
            if first is None or first.binary:
                return sock.abort()
            hello = protocol.parse_json(first.data)
            if hello["t"] != "hello":
                raise ProtocolError("expected hello")
        except (asyncio.TimeoutError, ProtocolError):
            return sock.close(1002, "bad hello")
        if not self._check_pin(peer, hello.get("pin")):
            await asyncio.sleep(1)
            sock.send_text(protocol.dumps({"t": "error", "code": "pin", "msg": "Wrong or missing PIN"}))
            return sock.close(1008, "pin")
        client_id = sanitize_name(hello.get("id"), "", 64) or "anon-%s-%d" % (peer, id(sock))
        name = sanitize_name(hello.get("name"))
        old = next((p.ws for p in self.manager.players.values()
                    if p.client_id == client_id and p.ws is not None), None)
        try:
            player, resumed = self.manager.join(client_id, name, ws=sock)
        except UInputError as e:
            log.error("%s", e)
            sock.send_text(protocol.dumps({"t": "error", "code": "uinput", "msg": str(e)}))
            return sock.close(1011, "uinput")
        if player is None:
            sock.send_text(protocol.dumps({"t": "error", "code": "full", "msg": "All player slots are taken"}))
            return sock.close(1008, "full")
        if old is not None and old is not sock:
            old.close(1000, "replaced by a new connection")
        self._welcome(player, sock, resumed)
        self._broadcast_roster()
        try:
            while True:
                msg = await asyncio.wait_for(sock.recv(), 20)
                if msg is None:
                    break
                try:
                    if msg.binary:
                        self._on_binary(player, msg.data)
                    else:
                        self._on_text(player, sock, protocol.parse_json(msg.data))
                except ProtocolError as e:
                    log.debug("bad message from P%d: %s", player.slot, e)
        except asyncio.TimeoutError:
            log.info("P%d timed out", player.slot)
        finally:
            if player.ws is sock:
                self.manager.leave(player)
                player.ws = None
                self._broadcast_roster()
            sock.abort()

    def _welcome(self, player, sock, resumed):
        sock.send_text(protocol.dumps({
            "t": "welcome", "v": protocol.PROTOCOL_VERSION, "slot": player.slot, "name": player.name,
            "color": player.color, "max": self.cfg["max_players"], "resumed": resumed,
            "features": self.features(), "info": self.info(), "default_preset": self.cfg["default_preset"],
            "mock": self.mock}))

    def _on_binary(self, player, data):
        kind, val = protocol.parse_binary(data)
        if kind == "state":
            self.manager.apply_state(player, val)
        elif self.cfg["actions"].get("mouse"):
            mouse = self._extra("mouse")
            if mouse:
                mouse.move(*val)

    def _on_text(self, player, sock, m):
        t = m["t"]
        if t == "ping":
            lat = m.get("lat")
            if isinstance(lat, (int, float)) and 0 <= lat < 60000:
                player.latency = int(lat)
            sock.send_text(protocol.dumps({"t": "pong", "ts": m.get("ts")}))
        elif t == "action":
            asyncio.create_task(self._do_action(sock, str(m.get("name"))))
        elif t == "key":
            self._do_key(sock, m)
        elif t == "name":
            self.manager.rename(player.slot, sanitize_name(m.get("name"), player.name))
            self._broadcast_roster()
        elif t == "admin":
            self._do_admin(player, sock, m)
        elif t == "info":
            sock.send_text(protocol.dumps({"t": "info", "info": self.info()}))

    async def _do_action(self, sock, name):
        ok, msg = await self.actions.run(name)
        log.info("action %s -> %s (%s)", name, ok, msg)
        sock.send_text(protocol.dumps({"t": "result", "name": name, "ok": ok, "msg": msg}))

    def _do_key(self, sock, m):
        if not self.cfg["actions"].get("keyboard"):
            return sock.send_text(protocol.dumps({"t": "result", "name": "key", "ok": False, "msg": "disabled"}))
        kb = self._extra("keyboard")
        if kb is None:
            return
        if isinstance(m.get("text"), str):
            kb.type_text(m["text"][:64])
        elif isinstance(m.get("code"), str):
            kb.press(m["code"])

    def _do_admin(self, player, sock, m):
        def reply(ok, msg):
            sock.send_text(protocol.dumps({"t": "result", "name": "admin", "ok": ok, "msg": msg}))
        if not self.cfg["allow_admin"]:
            return reply(False, "disabled in config.json")
        op, slot = m.get("op"), m.get("slot")
        if not isinstance(slot, int) or slot not in self.manager.players:
            return reply(False, "no such player")
        target = self.manager.players[slot]
        if op == "kick":
            self.manager.leave(target, reserve=False)
            if target.ws:
                target.ws.send_text(protocol.dumps({"t": "kicked"}))
                target.ws.close(1000, "kicked")
                target.ws = None
        elif op == "rename":
            self.manager.rename(slot, sanitize_name(m.get("name"), target.name))
        elif op == "assign":
            to = m.get("to")
            if not isinstance(to, int):
                return reply(False, "bad slot")
            for q in self.manager.assign(slot, to):
                if q.ws:
                    q.ws.send_text(protocol.dumps({"t": "you", "slot": q.slot, "name": q.name, "color": q.color}))
        else:
            return reply(False, "unknown op")
        self._broadcast_roster()
        reply(True, "ok")
