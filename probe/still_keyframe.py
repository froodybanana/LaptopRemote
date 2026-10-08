#!/usr/bin/env python3
"""Does a keyframe request produce a frame while the screen is not changing? Run on the laptop
from ~/laptopremote/agent. Prints the encoder's frame count before each of six requests."""
import os

runtime = os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")

import dbus.mainloop.glib  # noqa: E402
from gi.repository import GLib  # noqa: E402

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

from laptopremote_agent import hypr  # noqa: E402
from laptopremote_agent.capture import PortalCapture  # noqa: E402
from laptopremote_agent.pipeline import Gst, SenderPipeline  # noqa: E402

loop = GLib.MainLoop()
count, marks = [0], []
hypr.create_output("LAPTOPREMOTE")
hypr.set_mode("LAPTOPREMOTE", 1280, 720, 1)


def ready(fd, node):
    pipeline = SenderPipeline(fd, node, "127.0.0.1", 47999, 47998, 20000, print)

    def probe(pad, info):
        count[0] += 1
        return Gst.PadProbeReturn.OK

    pipeline.encoder.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, probe)
    pipeline.start()

    def key():
        marks.append(count[0])
        pipeline.force_keyframe()
        return len(marks) < 6

    def done():
        print("frames before each keyframe request:", marks, "final:", count[0])
        pipeline.stop()
        capture.close()
        hypr.remove_output("LAPTOPREMOTE")
        loop.quit()
        return False

    GLib.timeout_add(2000, lambda: GLib.timeout_add(500, key) and False)
    GLib.timeout_add(6500, done)


capture = PortalCapture("LAPTOPREMOTE", ready, print)
GLib.timeout_add(400, lambda: capture.start() and False)
loop.run()
