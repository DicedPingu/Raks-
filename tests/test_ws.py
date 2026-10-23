import unittest

import _path  # noqa: F401
import ws


class WebSocketFramingTests(unittest.TestCase):
    def test_accept_key_rfc_example(self):
        self.assertEqual(ws.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_handshake_response(self):
        r = ws.handshake_response("dGhlIHNhbXBsZSBub25jZQ==")
        self.assertTrue(r.startswith(b"HTTP/1.1 101"))
        self.assertIn(b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", r)

    def test_masked_roundtrip_sizes(self):
        for n in (0, 5, 125, 126, 300, 65535, 65536, 70000):
            payload = bytes(i % 251 for i in range(n))
            frame = ws.encode_frame(ws.OP_BIN, payload, mask=b"\x01\x02\x03\x04")
            frames = ws.FrameParser().feed(frame)
            self.assertEqual(frames, [(True, ws.OP_BIN, payload)])

    def test_rfc_masked_hello(self):
        data = bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])
        self.assertEqual(ws.FrameParser().feed(data), [(True, ws.OP_TEXT, b"Hello")])

    def test_incremental_and_multiple(self):
        a = ws.encode_frame(ws.OP_TEXT, b"one", mask=b"abcd")
        b = ws.encode_frame(ws.OP_TEXT, b"two", mask=b"wxyz")
        p = ws.FrameParser()
        out = []
        for byte in a + b:
            out += p.feed(bytes([byte]))
        self.assertEqual([f[2] for f in out], [b"one", b"two"])

    def test_server_frames_unmasked(self):
        self.assertEqual(ws.encode_frame(ws.OP_TEXT, b"hi"), b"\x81\x02hi")
        self.assertEqual(ws.FrameParser(require_mask=False).feed(b"\x81\x02hi"), [(True, ws.OP_TEXT, b"hi")])

    def test_rejects_bad_frames(self):
        with self.assertRaises(ws.WSProtocolError):
            ws.FrameParser().feed(b"\x81\x02hi")                      # unmasked client frame
        with self.assertRaises(ws.WSProtocolError):
            ws.FrameParser().feed(b"\xc1\x80abcd")                    # RSV1
        with self.assertRaises(ws.WSProtocolError):
            ws.FrameParser().feed(b"\x03\x80abcd")                    # reserved opcode
        with self.assertRaises(ws.WSProtocolError):
            ws.FrameParser().feed(ws.encode_frame(ws.OP_PING, b"x" * 126, mask=b"abcd"))
        with self.assertRaises(ws.WSProtocolError):
            ws.FrameParser(max_payload=10).feed(ws.encode_frame(ws.OP_BIN, b"x" * 11, mask=b"abcd"))


if __name__ == "__main__":
    unittest.main()
