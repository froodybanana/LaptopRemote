#!/usr/bin/env python3
"""PC side of the latency probe: receive the laptop's RTP stream, show it, report latency.

  pc_receive.py LAPTOP_ADDRESS [--seconds N] [--port 5600] [--jitter MS] [--decoder nvh265dec]

No inbound firewall rule is needed: a UDP packet sent from the receive port to the laptop's
sending port (port + 1) every second makes Windows Firewall treat the stream as a reply.
Latency is read from GStreamer's latency tracer (udpsrc to sink, and per element).
"""
import argparse
import collections
import os
import re
import socket
import subprocess
import tempfile
import threading
import time

GST_BIN = os.path.expandvars(r"%LOCALAPPDATA%\Programs\gstreamer\1.0\msvc_x86_64\bin")


def punch(laptop, port, stop):
    # the socket is closed between sends: while it stays bound Windows hands it the stream
    # instead of udpsrc. The real viewer sends from the one socket it also receives on.
    while not stop.is_set():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
        sock.sendto(b"punch", (laptop, port + 1))
        sock.close()
        stop.wait(1.0)


def summary(values):
    values = sorted(values)
    return "n={} median {:.2f} p95 {:.2f} max {:.2f} ms".format(
        len(values), values[len(values) // 2], values[int(len(values) * 0.95)], values[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("laptop")
    parser.add_argument("--seconds", type=int, default=14)
    parser.add_argument("--port", type=int, default=5600)
    parser.add_argument("--jitter", type=int, default=10)
    parser.add_argument("--decoder", default="nvh265dec")
    parser.add_argument("--sink", default="d3d11videosink sync=false")
    args = parser.parse_args()

    stop = threading.Event()
    threading.Thread(target=punch, args=(args.laptop, args.port, stop), daemon=True).start()

    trace = os.path.join(tempfile.gettempdir(), "laptopremote-trace.log")
    if os.path.exists(trace):
        os.remove(trace)
    env = dict(os.environ, GST_DEBUG_NO_COLOR="1", GST_TRACERS="latency(flags=pipeline+element)",
               GST_DEBUG="GST_TRACER:7", GST_DEBUG_FILE=trace)
    pipeline = (
        f"udpsrc port={args.port} reuse=true "
        'caps="application/x-rtp,media=video,encoding-name=H265,clock-rate=90000,payload=96" '
        f"! rtpjitterbuffer latency={args.jitter} ! rtph265depay ! h265parse "
        f"! {args.decoder} ! {args.sink}")
    process = subprocess.Popen(os.path.join(GST_BIN, "gst-launch-1.0.exe") + " -q " + pipeline, env=env)
    time.sleep(args.seconds)
    process.terminate()
    process.wait()
    stop.set()

    pipe, elements = [], collections.defaultdict(list)
    with open(trace, errors="ignore") as handle:
        for line in handle:
            match = re.search(r"time=\(guint64\)(\d+)", line)
            if not match:
                continue
            ms = int(match.group(1)) / 1e6
            if " latency," in line:
                pipe.append(ms)
            elif "element-latency" in line:
                elements[re.search(r"element=\(string\)([^,]+)", line).group(1)].append(ms)
    if not pipe:
        print("no frames reached the sink")
        return 1
    print("udpsrc to sink:", summary(pipe))
    for name, values in elements.items():
        print(f"  {name}: {summary(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
