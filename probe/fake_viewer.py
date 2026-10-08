#!/usr/bin/env python3
"""Stand-in for the viewer's control channel, for checking the agent without the viewer.

  fake_viewer.py LAPTOP_ADDRESS [--seconds 12] [--size 1600x900] [--resize-to 1280x720] [--pause-at 4]
                 [--secret TEXT] [--plain] [--move X,Y] [--keys CODE,CODE] [--clipboard TEXT]

Reads the secret and the certificate pin from the viewer's config.json, sends hello, a keyframe
request and a heartbeat every second, and prints what the agent says.
--secret sends another secret, --plain talks without TLS; the agent must refuse both.
--move sends the pointer there every second; --keys presses those Linux key codes in second 2 and
never lets go, which the agent must do itself when the session ends.
--clipboard sends that text as the PC's clipboard in second 2; clipboard texts from the laptop are printed.
Run pc_receive.py --port 47801 beside it to see the video.
"""
import argparse
import hashlib
import json
import os
import pathlib
import socket
import ssl
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "agent"))
from laptopremote_agent import protocol  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("laptop")
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--resize-to")
    parser.add_argument("--pause-at", type=int, help="second at which to pause; resumes three seconds later")
    parser.add_argument("--secret", help="send this instead of the secret in config.json")
    parser.add_argument("--plain", action="store_true", help="no TLS")
    parser.add_argument("--move", help="X,Y: pointer position sent every second")
    parser.add_argument("--keys", help="comma-separated Linux key codes pressed in second 2 and held")
    parser.add_argument("--clipboard", help="text sent as the PC's clipboard in second 2")
    args = parser.parse_args()
    config = json.loads((pathlib.Path(os.environ["APPDATA"]) / "LaptopRemote" / "config.json").read_text())
    width, height = (int(n) for n in args.size.split("x"))
    # the real secret only ever goes out under TLS
    secret = args.secret if args.secret is not None else "not-the-secret" if args.plain else config["secret"]
    sock = socket.create_connection((args.laptop, 47800), timeout=3)
    if not args.plain:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # the pin below is the check
        sock = context.wrap_socket(sock)
        if hashlib.sha256(sock.getpeercert(True)).hexdigest() != config["certificateSha256"]:
            print("the agent's certificate is not the pinned one")
            return 2
        print(f"  0.0 {sock.version()} {sock.cipher()[0]}, certificate matches the pin")
    sock.settimeout(0.2)
    try:
        sock.sendall(protocol.encode({"type": "hello", "version": 1, "width": width, "height": height,
                                      "scale": 1, "video_port": 47801, "secret": secret}))
        reader, started = protocol.FrameReader(), time.monotonic()
        for second in range(args.seconds):
            if args.resize_to and second == args.seconds // 2:
                width, height = (int(n) for n in args.resize_to.split("x"))
                sock.sendall(protocol.encode({"type": "resize", "width": width, "height": height, "scale": 1}))
                print(f"{time.monotonic() - started:5.1f} sent resize {width}x{height}")
            if args.pause_at is not None and second in (args.pause_at, args.pause_at + 3):
                kind = "pause" if second == args.pause_at else "resume"
                sock.sendall(protocol.encode({"type": kind}))
                print(f"{time.monotonic() - started:5.1f} sent {kind}")
            if args.move:
                x, y = (int(n) for n in args.move.split(","))
                sock.sendall(protocol.encode({"type": "mouse_move", "x": x, "y": y}))
            if args.keys and second == 2:
                for code in args.keys.split(","):
                    sock.sendall(protocol.encode({"type": "key", "code": int(code), "down": True}))
                print(f"{time.monotonic() - started:5.1f} pressed {args.keys}")
            if args.clipboard and second == 2:
                sock.sendall(protocol.encode({"type": "clipboard", "text": args.clipboard}))
                print(f"{time.monotonic() - started:5.1f} sent clipboard")
            sock.sendall(protocol.encode({"type": "keyframe"}) + protocol.encode({"type": "heartbeat"}))
            end = time.monotonic() + 1
            while time.monotonic() < end:
                try:
                    data = sock.recv(65536)
                except (socket.timeout, ssl.SSLWantReadError):
                    continue
                if not data:
                    print("agent closed the connection")
                    return 1
                for message in reader.feed(data):
                    if message["type"] == "clipboard":
                        text = message["text"]
                        print(f"{time.monotonic() - started:5.1f} clipboard, {len(text)} characters: {text[:60]!r}")
                    elif message["type"] != "heartbeat":
                        print(f"{time.monotonic() - started:5.1f} {message}")
        print(f"{time.monotonic() - started:5.1f} still connected, saying goodbye")
        sock.sendall(protocol.encode({"type": "goodbye"}))
    except (ConnectionError, ssl.SSLError, protocol.ProtocolError) as error:
        print(f"agent closed the connection ({type(error).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
