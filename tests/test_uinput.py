import struct
import unittest

import _path  # noqa: F401
import uinput as U
from protocol import PadState, pack_state, BUTTON_BIT


class UInputPackingTests(unittest.TestCase):
    def test_event_layout(self):
        e = U.pack_event(U.EV_KEY, U.BTN_CODES["south"], 1)
        self.assertEqual(len(e), U.EVENT_SIZE)
        sec, usec, t, c, v = struct.unpack(U.EVENT_FMT, e)
        self.assertEqual((sec, usec, t, c, v), (0, 0, 1, 0x130, 1))

    def test_user_dev_layout(self):
        blob = U.pack_user_dev("Raks Player 1", 3, 0x045E, 0x028E, 0x110, U.GAMEPAD_ABS)
        self.assertEqual(len(blob), 80 + 8 + 4 + 4 * 64 * 4)
        self.assertEqual(blob[:13], b"Raks Player 1")
        bus, vid, pid, ver = struct.unpack_from("<HHHH", blob, 80)
        self.assertEqual((bus, vid, pid, ver), (3, 0x045E, 0x028E, 0x110))
        absmax = struct.unpack_from("<64i", blob, 92)
        absmin = struct.unpack_from("<64i", blob, 92 + 256)
        self.assertEqual((absmin[U.ABS_X], absmax[U.ABS_X]), (-32768, 32767))
        self.assertEqual((absmin[U.ABS_Z], absmax[U.ABS_Z]), (0, 255))
        self.assertEqual((absmin[U.ABS_HAT0X], absmax[U.ABS_HAT0Y]), (-1, 1))

    def test_name_truncated(self):
        blob = U.pack_user_dev("x" * 200, 3, 1, 1, 1)
        self.assertEqual(blob[79], 0)

    def test_button_codes_match_linux(self):
        self.assertEqual(U.BTN_CODES["south"], 0x130)   # BTN_SOUTH
        self.assertEqual(U.BTN_CODES["north"], 0x133)   # BTN_NORTH
        self.assertEqual(U.BTN_CODES["west"], 0x134)    # BTN_WEST
        self.assertEqual(U.BTN_CODES["mode"], 0x13C)    # BTN_MODE
        self.assertEqual(len(set(U.BTN_CODES.values())), 13)

    def test_diff_events(self):
        a = PadState()
        b = PadState(buttons=1 << BUTTON_BIT["east"] | 1 << BUTTON_BIT["start"], lx=1000, hy=-1)
        ev = U.diff_events(a, b)
        self.assertIn((U.EV_KEY, 0x131, 1), ev)
        self.assertIn((U.EV_KEY, 0x13B, 1), ev)
        self.assertIn((U.EV_ABS, U.ABS_X, 1000), ev)
        self.assertIn((U.EV_ABS, U.ABS_HAT0Y, -1), ev)
        self.assertEqual(U.diff_events(b, b), [])
        back = U.diff_events(b, a)
        self.assertIn((U.EV_KEY, 0x131, 0), back)

    def test_digital_trigger_implies_analog(self):
        ev = U.diff_events(PadState(), PadState(buttons=1 << BUTTON_BIT["tl2"]))
        self.assertIn((U.EV_KEY, 0x138, 1), ev)
        self.assertIn((U.EV_ABS, U.ABS_Z, 255), ev)

    def test_text_to_keys(self):
        b = U.text_to_key_events("aA!?")
        self.assertEqual(len(b), 4)
        self.assertEqual(b[0], [(U.EV_KEY, 30, 1), (U.EV_KEY, 30, 0)])
        self.assertEqual(b[1][0], (U.EV_KEY, U.KEY_LEFTSHIFT, 1))
        self.assertEqual(U.text_to_key_events("\u00e9"), [])

    def test_mock_devices_do_not_touch_uinput(self):
        pad = U.Gamepad("Raks Player 1", mock=True)
        pad.emit([(U.EV_KEY, 0x130, 1)])
        pad.close()
        kb, ms = U.Keyboard(mock=True), U.Mouse(mock=True)
        kb.type_text("hi")
        self.assertTrue(kb.press("enter"))
        self.assertFalse(kb.press("nonsense"))
        ms.move(3, 4, 0, 1)


if __name__ == "__main__":
    unittest.main()
