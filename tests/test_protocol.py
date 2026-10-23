import unittest

import _path  # noqa: F401
import protocol as P


class ProtocolTests(unittest.TestCase):
    def test_state_roundtrip(self):
        s = P.PadState(buttons=0b1010101, hx=-1, hy=1, lx=-32768, ly=32767, rx=100, ry=-100, lt=255, rt=7)
        data = P.pack_state(s)
        self.assertEqual(len(data), P.STATE_SIZE)
        self.assertEqual(data[0], P.MSG_STATE)
        kind, parsed = P.parse_binary(data)
        self.assertEqual(kind, "state")
        self.assertEqual(parsed, s)

    def test_state_clamps(self):
        data = P.pack_state(P.PadState(buttons=0xFFFF, hx=5, hy=-5, lx=99999, lt=999))
        _, s = P.parse_binary(data)
        self.assertEqual(s.buttons, P.BUTTON_MASK)
        self.assertEqual((s.hx, s.hy, s.lx, s.lt), (1, -1, 32767, 255))

    def test_mouse_roundtrip(self):
        kind, m = P.parse_binary(P.pack_mouse(P.MouseMove(-5, 300, -2, 5)))
        self.assertEqual(kind, "mouse")
        self.assertEqual(m, P.MouseMove(-5, 300, -2, 5))

    def test_bad_binary(self):
        for bad in (b"", b"\x01\x00", b"\x09" + b"\x00" * 14, b"\x02\x00"):
            with self.assertRaises(P.ProtocolError):
                P.parse_binary(bad)

    def test_json(self):
        self.assertEqual(P.parse_json('{"t":"ping","ts":1}')["ts"], 1)
        for bad in ("nope", "[]", '{"x":1}', '{"t":5}', "{" + '"t":"a",' * 1 + '"p":"' + "x" * 5000 + '"}'):
            with self.assertRaises(P.ProtocolError):
                P.parse_json(bad)

    def test_button_table(self):
        self.assertEqual(len(P.BUTTONS), 13)
        self.assertEqual(P.BUTTON_BIT["south"], 0)
        self.assertTrue(set(P.BUTTONS) <= set(P.CONTROL_CODES))

    def test_sanitize_name(self):
        self.assertEqual(P.sanitize_name("  Bob\n\t"), "Bob")
        self.assertEqual(P.sanitize_name("x" * 100), "x" * 24)
        self.assertEqual(P.sanitize_name(5, "d"), "d")


if __name__ == "__main__":
    unittest.main()
