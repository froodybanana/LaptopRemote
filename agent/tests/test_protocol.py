import json
import pathlib
import struct
import unittest

from laptopremote_agent import protocol

SAMPLES = pathlib.Path(__file__).resolve().parents[2] / "protocol" / "samples"


class ProtocolTests(unittest.TestCase):
    def test_valid_samples_round_trip(self):
        files = sorted((SAMPLES / "valid").glob("*.json"))
        self.assertEqual(len(files), 15)
        for path in files:
            message = json.loads(path.read_text(encoding="utf-8"))
            frame = protocol.encode(message)
            self.assertEqual(protocol.FrameReader().feed(frame), [message], path.name)

    def test_invalid_samples_rejected(self):
        files = sorted((SAMPLES / "invalid").glob("*.json"))
        self.assertEqual(len(files), 12)
        for path in files:
            body = path.read_bytes()
            with self.assertRaises(protocol.ProtocolError, msg=path.name):
                protocol.FrameReader().feed(struct.pack(">I", len(body)) + body)

    def test_frames_split_across_feeds(self):
        data = protocol.encode({"type": "heartbeat"}) + protocol.encode({"type": "goodbye"})
        reader, seen = protocol.FrameReader(), []
        for index in range(len(data)):
            seen += reader.feed(data[index:index + 1])
        self.assertEqual(seen, [{"type": "heartbeat"}, {"type": "goodbye"}])

    def test_oversize_frame_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.FrameReader().feed(struct.pack(">I", protocol.MAX_FRAME + 1))

    def test_bool_is_not_a_number(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate({"type": "resize", "width": True, "height": 720, "scale": 1})

    def test_bool_fields_need_a_bool(self):
        self.assertEqual(protocol.validate({"type": "key", "code": 30, "down": True})["down"], True)
        for bad in (1, 0, "true", None):
            with self.assertRaises(protocol.ProtocolError, msg=repr(bad)):
                protocol.validate({"type": "key", "code": 30, "down": bad})

    def test_text_is_not_escaped(self):
        # a megabyte of clipboard text must not grow to six on the way
        frame = protocol.encode({"type": "clipboard", "text": "blåbær 😀"})
        self.assertIn("blåbær 😀".encode(), frame)
        self.assertEqual(protocol.FrameReader().feed(frame), [{"type": "clipboard", "text": "blåbær 😀"}])

    def test_half_a_character_is_still_encoded(self):
        frame = protocol.encode({"type": "clipboard", "text": "a" + chr(0xD800) + "b"})
        self.assertEqual(protocol.FrameReader().feed(frame), [{"type": "clipboard", "text": "a?b"}])

    def test_encode_refuses_a_long_frame(self):
        protocol.encode({"type": "clipboard", "text": "x" * (protocol.MAX_FRAME - 100)})
        with self.assertRaises(protocol.ProtocolError):
            protocol.encode({"type": "clipboard", "text": "x" * protocol.MAX_FRAME})

    def test_deeply_nested_json_rejected(self):
        body = b"[" * 100000
        with self.assertRaises(protocol.ProtocolError):
            protocol.FrameReader().feed(struct.pack(">I", len(body)) + body)

    def test_error_text_stays_short(self):
        # the text goes back to the sender, who may not have proved anything yet
        for kind in ("A" * 100000, ["A" * 100000]):
            with self.assertRaises(protocol.ProtocolError) as caught:
                protocol.validate({"type": kind})
            self.assertLess(len(str(caught.exception)), 200)

    def test_bad_json_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.FrameReader().feed(struct.pack(">I", 3) + b"{no")


if __name__ == "__main__":
    unittest.main()
