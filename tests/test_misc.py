import unittest

import _path  # noqa: F401
import mdns
import players
import qr
import raks_host
import uinput


class FakeDev:
    def __init__(self, name):
        self.name, self.closed, self.events = name, False, []

    def emit(self, ev):
        self.events += ev

    def close(self):
        self.closed = True


class PlayerManagerTests(unittest.TestCase):
    def setUp(self):
        self.now = [0]
        self.devs = []

        def factory(n):
            d = FakeDev(n)
            self.devs.append(d)
            return d
        self.m = players.PlayerManager(2, factory, 100, clock=lambda: self.now[0])

    def test_slots_names_and_cleanup(self):
        a, _ = self.m.join("a")
        b, _ = self.m.join("b")
        self.assertEqual((a.slot, b.slot), (1, 2))
        self.assertEqual(self.devs[0].name, "Raks Player 1")
        self.assertEqual(self.m.join("c"), (None, False))
        self.m.leave(a)
        self.assertTrue(self.devs[0].closed)

    def test_reconnect_keeps_slot_and_reservation_expires(self):
        a, _ = self.m.join("a")
        self.m.join("b")
        self.m.leave(a)
        p, resumed = self.m.join("a")
        self.assertEqual((p.slot, resumed), (1, True))
        self.m.leave(p)
        q, resumed = self.m.join("new")                   # reserved slot is stolen only when full
        self.assertEqual((q.slot, resumed), (1, False))

    def test_apply_state_emits_events(self):
        from protocol import PadState
        a, _ = self.m.join("a")
        self.m.apply_state(a, PadState(buttons=1))
        self.assertIn((uinput.EV_KEY, 0x130, 1), self.devs[0].events)


class QRTests(unittest.TestCase):
    def test_matrix_shape(self):
        m = qr.make_qr("http://192.168.1.50:8080/play/")
        n = len(m)
        self.assertTrue(21 <= n <= 57 and (n - 21) % 4 == 0)
        self.assertTrue(all(len(r) == n for r in m))
        self.assertTrue(all(m[0][i] for i in range(7)))   # finder pattern top edge
        self.assertIn("<svg", qr.to_svg(m))
        self.assertTrue(qr.to_ascii(m, color=False))

    def test_too_long(self):
        with self.assertRaises(Exception):
            qr.make_qr("x" * 1000)


class MDNSTests(unittest.TestCase):
    def test_response_contains_name_and_ip(self):
        r = mdns.build_response("raks.local", "192.168.1.9")
        self.assertIn(b"\x04raks\x05local", r)
        self.assertIn(bytes([192, 168, 1, 9]), r)

    def test_parse_question(self):
        q = (b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + b"\x04raks\x05local\x00\x00\x01\x00\x01")
        qs = mdns.parse_questions(q)
        self.assertEqual((qs[0][0].lower().rstrip('.'), qs[0][1]), ('raks.local', 1))
        self.assertEqual(list(mdns.parse_questions(b"junk")), [])


class HostIpDiscoveryTests(unittest.TestCase):
    def test_discover_ips_includes_preferred_and_filters_loopback(self):
        orig_socket = raks_host.socket.socket
        orig_getaddrinfo = raks_host.socket.getaddrinfo

        class FakeSocket:
            calls = 0

            def __init__(self, *a, **kw):
                self.ip = "127.0.0.1"

            def connect(self, target):
                FakeSocket.calls += 1
                if FakeSocket.calls == 1:
                    self.ip = "192.168.44.1"
                else:
                    raise OSError("no route")

            def getsockname(self):
                return (self.ip, 12345)

            def close(self):
                return None

        def fake_getaddrinfo(*args, **kwargs):
            return [(None, None, None, None, ("127.0.0.1", 0)),
                    (None, None, None, None, ("172.20.10.1", 0)),
                    (None, None, None, None, ("192.168.44.1", 0))]

        raks_host.socket.socket = FakeSocket
        raks_host.socket.getaddrinfo = fake_getaddrinfo
        try:
            ips = raks_host.discover_ips("10.0.0.50")
        finally:
            raks_host.socket.socket = orig_socket
            raks_host.socket.getaddrinfo = orig_getaddrinfo

        self.assertEqual(ips, ["10.0.0.50", "192.168.44.1", "172.20.10.1"])

    def test_discover_ips_falls_back_to_loopback(self):
        orig_socket = raks_host.socket.socket
        orig_getaddrinfo = raks_host.socket.getaddrinfo

        class DeadSocket:
            def __init__(self, *a, **kw):
                pass

            def connect(self, target):
                raise OSError("no route")

            def close(self):
                return None

        raks_host.socket.socket = DeadSocket
        raks_host.socket.getaddrinfo = lambda *a, **kw: []
        try:
            ips = raks_host.discover_ips()
        finally:
            raks_host.socket.socket = orig_socket
            raks_host.socket.getaddrinfo = orig_getaddrinfo

        self.assertEqual(ips, ["127.0.0.1"])


if __name__ == "__main__":
    unittest.main()
