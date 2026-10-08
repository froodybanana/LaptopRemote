#!/usr/bin/env python3
"""Laptop side of the round-trip latency probe.

Reads lines "X Y" on stdin and moves the Hyprland cursor there at once, by writing to the
Hyprland command socket directly (no hyprctl process start in the timed path).
"""
import os
import socket
import sys

runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
hypr = os.path.join(runtime, "hypr")
signature = max(os.listdir(hypr), key=lambda name: os.path.getmtime(os.path.join(hypr, name)))
path = os.path.join(hypr, signature, ".socket.sock")

for line in sys.stdin:
    x, y = line.split()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        sock.sendall(f"/eval hl.dispatch(hl.dsp.cursor.move({{x={x}, y={y}}}))".encode())
        sock.recv(256)
