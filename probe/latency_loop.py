#!/usr/bin/env python3
"""Round-trip latency probe, run on the PC.

Tells the laptop to move its cursor and times how long until the frame showing it reaches the
video sink on this PC. Each move is preceded by a 5-byte marker packet sent to the receiver's
own UDP port, so the move and the frame's arrival are stamped by the same GStreamer log clock.

Covered: command to the laptop over ssh, Hyprland drawing the frame, capture, encode, network,
jitter buffer, depacketize, decode, hand-over to the video sink.
Not covered: presentation by the Windows compositor and the monitor (up to one refresh).

  latency_loop.py USER@LAPTOP PC_ADDRESS [--jitter MS] [--rounds N] [--mode WxH]
"""
import argparse
import os
import re
import socket
import statistics
import subprocess
import tempfile
import threading
import time

from pc_receive import GST_BIN, punch

VIDEO_LEFT = 1600   # layout x of the headless output: eDP-1 is 1920 wide at scale 1.2
MARKER = b"mark!"


def summary(values):
    values = sorted(values)
    return "min {:.1f} median {:.1f} mean {:.1f} p90 {:.1f} max {:.1f}".format(
        values[0], values[len(values) // 2], statistics.mean(values),
        values[int(len(values) * 0.9)], values[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("laptop")
    parser.add_argument("pc")
    parser.add_argument("--jitter", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=40)
    parser.add_argument("--mode", default="1600x900")
    parser.add_argument("--port", type=int, default=5600)
    args = parser.parse_args()
    host = args.laptop.split("@")[-1]

    stop = threading.Event()
    threading.Thread(target=punch, args=(host, args.port, stop), daemon=True).start()
    log = os.path.join(tempfile.gettempdir(), "laptopremote-loop.log")
    if os.path.exists(log):
        os.remove(log)
    env = dict(os.environ, GST_DEBUG_NO_COLOR="1", GST_DEBUG="GST_SCHEDULING:7", GST_DEBUG_FILE=log)
    receiver = subprocess.Popen(
        os.path.join(GST_BIN, "gst-launch-1.0.exe") + f" -q udpsrc port={args.port} reuse=true "
        'caps="application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96" '
        f"! rtpjitterbuffer latency={args.jitter} ! rtph264depay name=depay ! h264parse "
        "! d3d11h264dec ! d3d11videosink name=sink sync=false", env=env, stderr=subprocess.DEVNULL)
    seconds = 16 + args.rounds // 2
    sender = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", args.laptop,
         f"NOMOVE=1 KEYINT=60 ~/laptopremote-probe/encode_probe.sh {args.pc} dmabuf-lpenc {seconds} {args.mode}"],
        stdout=subprocess.PIPE, text=True)
    flipper = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", args.laptop, "python3 -u ~/laptopremote-probe/flipper.py"],
        stdin=subprocess.PIPE, text=True)
    marker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def move(x, y):
        flipper.stdin.write(f"{VIDEO_LEFT + x} {y}\n")
        flipper.stdin.flush()

    try:
        time.sleep(5)
        for index in range(120):  # motion so the encoder emits a keyframe the PC can start on
            move(300 + index % 2 * 300, 300)
            time.sleep(0.03)
        time.sleep(1)
        for index in range(args.rounds):
            time.sleep(0.25 + (index * 7 % 17) / 1000)  # vary the phase against the laptop's vblank
            marker.sendto(MARKER, ("127.0.0.1", args.port))
            move(300 + index % 2 * 300, 500)
        time.sleep(1)
    finally:
        receiver.terminate()
        receiver.wait()
        move(960 - VIDEO_LEFT, 540)
        flipper.stdin.close()
        stop.set()
        laptop = [line.strip() for line in sender.stdout if "capture-to-mark" in line or "FAIL" in line]

    pattern = re.compile(r"^(\d+):(\d+):(\d+\.\d+) .*<([a-z0-9]+):sink> calling chainfunction .*size (\d+)")
    events = []
    with open(log, errors="ignore") as handle:
        for line in handle:
            match = pattern.match(line)
            if match:
                h, m, s, element, size = match.groups()
                events.append((int(h) * 3600 + int(m) * 60 + float(s), element, int(size)))
    marks = [t for t, element, size in events if element.startswith("rtpjitter") and size == len(MARKER)]
    arrive, depay, sink = [], [], []
    for start, end in zip(marks, marks[1:] + [float("inf")]):
        window = [(t, element) for t, element, size in events if start < t < end and size != len(MARKER)]

        def first(prefix):
            return next((t for t, element in window if element.startswith(prefix)), None)

        packet, out, shown = first("rtpjitter"), first("depay"), first("sink")
        if packet is None or out is None or shown is None:
            continue
        arrive.append((packet - start) * 1000)
        depay.append((out - packet) * 1000)
        sink.append((shown - start) * 1000)
    print(f"markers {len(marks)}, moves answered by a frame {len(sink)}, jitter buffer set to {args.jitter} ms")
    if sink:
        print("move sent -> first packet at PC ms:   ", summary(arrive))
        print("first packet -> out of jitter buffer: ", summary(depay))
        print("move sent -> frame at video sink ms:  ", summary(sink))
    for line in laptop:
        print("laptop:", line[:120])
    return 0 if sink else 1


if __name__ == "__main__":
    raise SystemExit(main())
