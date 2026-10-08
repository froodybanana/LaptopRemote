#!/usr/bin/env python3
"""Find which PC pipeline stage holds a lone frame back. Run on the PC.

The laptop sends single frames half a second apart (one cursor move each). GStreamer's
scheduling log gives the time each buffer enters each element, so a stage that only releases
a frame when the next one arrives shows up as a ~500 ms gap.

  stage_probe.py USER@LAPTOP PC_ADDRESS [--tail "h264parse ! d3d11h264dec ! d3d11videosink sync=false"]
"""
import argparse
import os
import re
import subprocess
import tempfile
import threading
import time

from pc_receive import GST_BIN, punch

VIDEO_LEFT = 1600


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("laptop")
    parser.add_argument("pc")
    parser.add_argument("--jitter", type=int, default=10)
    parser.add_argument("--tail", default="h264parse ! d3d11h264dec ! d3d11videosink sync=false")
    parser.add_argument("--port", type=int, default=5600)
    args = parser.parse_args()
    host = args.laptop.split("@")[-1]

    stop = threading.Event()
    threading.Thread(target=punch, args=(host, args.port, stop), daemon=True).start()
    log = os.path.join(tempfile.gettempdir(), "laptopremote-stage.log")
    if os.path.exists(log):
        os.remove(log)
    env = dict(os.environ, GST_DEBUG_NO_COLOR="1", GST_DEBUG="GST_SCHEDULING:7", GST_DEBUG_FILE=log)
    sender = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", args.laptop,
         f"NOMOVE=1 KEYINT=60 ~/laptopremote-probe/encode_probe.sh {args.pc} dmabuf-lpenc 22"],
        stdout=subprocess.DEVNULL)
    flipper = subprocess.Popen(
        ["ssh", "-o", "BatchMode=yes", args.laptop, "python3 -u ~/laptopremote-probe/flipper.py"],
        stdin=subprocess.PIPE, text=True)

    def move(x, y):
        flipper.stdin.write(f"{VIDEO_LEFT + x} {y}\n")
        flipper.stdin.flush()

    time.sleep(5)
    for index in range(150):  # motion until a keyframe has got through
        move(300 + index % 2 * 300, 300)
        time.sleep(0.03)
    time.sleep(1)
    receiver = None
    try:
        receiver = subprocess.Popen(
            os.path.join(GST_BIN, "gst-launch-1.0.exe") + f" -q udpsrc port={args.port} reuse=true "
            'caps="application/x-rtp,media=video,encoding-name=H264,clock-rate=90000,payload=96" '
            f"! rtpjitterbuffer latency={args.jitter} ! rtph264depay name=depay ! {args.tail}", env=env)
        time.sleep(2)
        for index in range(90):   # keyframe for the freshly started receiver
            move(300 + index % 2 * 300, 300)
            time.sleep(0.03)
        time.sleep(1.5)
        for index in range(8):    # the lone frames under test
            move(300 + index % 2 * 300, 500)
            time.sleep(0.5)
        time.sleep(1)
    finally:
        if receiver:
            receiver.terminate()
            receiver.wait()
        move(960 - VIDEO_LEFT, 540)
        flipper.stdin.close()
        stop.set()
        sender.wait()

    arrivals = {}
    pattern = re.compile(r"^(\d+):(\d+):(\d+\.\d+) .*<([a-z0-9]+):sink> calling chainfunction ")
    with open(log, errors="ignore") as handle:
        for line in handle:
            match = pattern.match(line)
            if match:
                h, m, s, element = match.groups()
                arrivals.setdefault(element, []).append(int(h) * 3600 + int(m) * 60 + float(s))
    if "depay" not in arrivals:
        print("no packets seen; elements logged:", list(arrivals))
        return 1
    # lone frames: packet bursts at the depayloader separated by more than 300 ms
    bursts = [arrivals["depay"][0]]
    for stamp in arrivals["depay"]:
        if stamp - bursts[-1] > 0.3:
            bursts.append(stamp)
        else:
            bursts[-1] = max(bursts[-1], stamp) if stamp - bursts[-1] < 0.05 and len(bursts) > 1 else bursts[-1]
    lone = bursts[-8:]
    print(f"lone frames seen at depayloader: {len(lone)}")
    for element, stamps in arrivals.items():
        if element == "depay" or element.startswith("rtpjitter"):
            continue
        delays = []
        for start in lone:
            later = [s for s in stamps if s >= start - 0.001]
            delays.append((later[0] - start) * 1000 if later else float("inf"))
        print(f"  enters {element}: " + " ".join(f"{d:.0f}" for d in delays) + " ms after its packets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
