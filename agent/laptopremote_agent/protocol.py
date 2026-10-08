"""Control protocol: 4-byte big-endian length + UTF-8 JSON object. See protocol/README.md."""
import json
import struct

VERSION = 1
MAX_FRAME = 2 * 1024 * 1024
NUMBER = (int, float)
FIELDS = {
    "hello": {"version": int, "width": int, "height": int, "scale": NUMBER, "video_port": int, "secret": str},
    "welcome": {"version": int, "video_send_port": int},
    "resize": {"width": int, "height": int, "scale": NUMBER},
    "keyframe": {},
    "pause": {},
    "resume": {},
    "mouse_move": {"x": int, "y": int},
    "mouse_button": {"button": str, "down": bool},
    "mouse_wheel": {"dx": NUMBER, "dy": NUMBER},
    "key": {"code": int, "down": bool},
    "release": {},
    "clipboard": {"text": str},
    "heartbeat": {},
    "goodbye": {},
    "error": {"message": str},
}


class ProtocolError(Exception):
    pass


def validate(message):
    if not isinstance(message, dict):
        raise ProtocolError("message is not an object")
    kind = message.get("type")
    if not isinstance(kind, str) or kind not in FIELDS:
        raise ProtocolError(f"unknown message type {repr(kind)[:60]}")  # the text is sent back: keep it short
    for name, wanted in FIELDS[kind].items():
        value = message.get(name)
        # a bool is an int in Python; it only counts where a bool is asked for
        if not isinstance(value, wanted) or (isinstance(value, bool) and wanted is not bool):
            raise ProtocolError(f"{kind}.{name} is missing or of the wrong kind")
    return message


def encode(message):
    # not escaped to ASCII: clipboard text would grow up to sixfold. Half a surrogate pair becomes "?"
    body = json.dumps(validate(message), separators=(",", ":"), ensure_ascii=False).encode("utf-8", "replace")
    if len(body) > MAX_FRAME:
        raise ProtocolError("frame too long")
    return struct.pack(">I", len(body)) + body


class FrameReader:
    def __init__(self):
        self.buffer = b""

    def feed(self, data):
        self.buffer += data
        messages = []
        while len(self.buffer) >= 4:
            (length,) = struct.unpack(">I", self.buffer[:4])
            if length > MAX_FRAME:
                raise ProtocolError("frame too long")
            if len(self.buffer) < 4 + length:
                break
            body, self.buffer = self.buffer[4:4 + length], self.buffer[4 + length:]
            try:
                message = json.loads(body)
            except (ValueError, RecursionError) as error:
                raise ProtocolError(f"bad JSON: {error}") from None
            messages.append(validate(message))
        return messages
