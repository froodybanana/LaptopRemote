#!/usr/bin/env python3
"""Capture probe: unattended portal screen share of one Hyprland output into GStreamer.

Asks the ScreenCast portal for a monitor stream, feeds it to a GStreamer pipeline and
reports negotiated caps, frame count and frame intervals.

  capture_probe.py OUTPUT [--seconds N] [--token FILE] [--no-flag] [--pipeline "..."]

OUTPUT       Hyprland output name the picker script should select
--token      file holding the portal restore token; read if present, rewritten after Start
--no-flag    do not drop the picker flag file (tests the restore token on its own)
--pipeline   gst-launch text placed after pipewiresrc; default counts frames into fakesink
"""
import argparse
import os
import sys
import time

import dbus
import dbus.mainloop.glib
import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"


class Probe:
    def __init__(self, args):
        self.args = args
        self.loop = GLib.MainLoop()
        self.bus = dbus.SessionBus()
        self.portal = dbus.Interface(self.bus.get_object(PORTAL, PORTAL_PATH), SCREENCAST)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.counter = 0
        self.session = None
        self.pipeline = None
        self.stamps = []
        self.captured = []
        self.stage = []
        self.caps = None
        self.started = time.monotonic()
        self.failed = None

    def log(self, text):
        print(f"[{time.monotonic() - self.started:7.3f}] {text}", flush=True)

    def call(self, method, handler, *call_args, options=None):
        self.counter += 1
        token = f"probe{os.getpid()}_{self.counter}"
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        self.bus.add_signal_receiver(handler, "Response", REQUEST, PORTAL, path)
        options = dict(options or {})
        options["handle_token"] = token
        method(*call_args, dbus.Dictionary(options, signature="sv"))

    def fail(self, text):
        self.failed = text
        self.log(f"FAIL {text}")
        self.loop.quit()

    def run(self):
        if self.args.source:
            GLib.idle_add(self.start_pipeline, None)
            self.loop.run()
            self.pipeline.set_state(Gst.State.NULL)
            return 1 if self.failed else 0
        self.call(self.portal.CreateSession, self.on_session,
                  options={"session_handle_token": f"probe{os.getpid()}"})
        self.loop.run()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        return 1 if self.failed else 0

    def on_session(self, code, results):
        if code != 0:
            return self.fail(f"CreateSession response {code}")
        self.session = results["session_handle"]
        self.log("session created")
        options = {
            "types": dbus.UInt32(1),         # monitors
            "multiple": False,
            "cursor_mode": dbus.UInt32(2),   # cursor drawn into the stream
            "persist_mode": dbus.UInt32(2),  # token survives until revoked
        }
        token = self.read_token()
        if token:
            options["restore_token"] = token
            self.log("restore token supplied")
        # xdg-desktop-portal-hyprland runs the picker inside SelectSources and blocks on it
        if not self.args.no_flag:
            runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            with open(os.path.join(runtime, "laptopremote-pick"), "w") as flag:
                flag.write(self.args.output)
        self.log("selecting (picker runs now if the token does not restore)")
        self.call(self.portal.SelectSources, self.on_selected, self.session, options=options)

    def on_selected(self, code, results):
        if code != 0:
            return self.fail(f"SelectSources response {code}")
        self.log("selected, starting")
        self.call(self.portal.Start, self.on_started, self.session, "")

    def on_started(self, code, results):
        if code != 0:
            return self.fail(f"Start response {code} (1 = cancelled by picker)")
        streams = results["streams"]
        node, props = streams[0]
        self.log(f"stream node {node} props {dict((str(k), str(v)) for k, v in props.items())}")
        token = results.get("restore_token")
        if token and self.args.token:
            with open(self.args.token, "w") as handle:
                handle.write(str(token))
            self.log("restore token saved")
        elif not token:
            self.log("no restore token returned")
        fd = self.portal.OpenPipeWireRemote(self.session, dbus.Dictionary({}, signature="sv")).take()
        select = {"path": f"path={int(node)}",
                  "serial": f"target-object={props.get('pipewire-serial', node)}"}[self.args.by]
        remote = "" if self.args.own_connection else f"fd={fd} "
        GLib.timeout_add(self.args.delay_ms, self.start_pipeline, remote + select)

    def start_pipeline(self, source):
        # pipewiresrc needs video caps downstream or WirePlumber reports "target not found"
        tail = self.args.pipeline or "video/x-raw ! fakesink name=sink sync=false"
        if self.args.source:
            text = f"{self.args.source} name=src ! {tail}"
        else:
            text = f"pipewiresrc name=src {source} do-timestamp=true keepalive-time={self.args.keepalive} ! {tail}"
        self.log(f"pipeline: {text}")
        self.pipeline = Gst.parse_launch(text)
        src = self.pipeline.get_by_name("src")
        src.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, self.on_buffer)
        # an element named "mark" in --pipeline times capture-to-there per frame
        mark = self.pipeline.get_by_name("mark")
        if mark:
            mark.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, self.on_mark)
        # pipewiresrc only reports itself live after caps are set, which is too late for
        # vah264enc: it then holds frames back. Answering the latency query for it on the
        # src pad of the element named "live" makes the encoder output every frame at once.
        live = self.pipeline.get_by_name("live")
        if live:
            live.get_static_pad("src").add_probe(Gst.PadProbeType.QUERY_UPSTREAM, self.on_query)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self.on_error)
        self.pipeline.set_state(Gst.State.PLAYING)
        GLib.timeout_add_seconds(self.args.seconds, self.finish)
        return False

    def on_buffer(self, pad, info):
        if self.caps is None:
            caps = pad.get_current_caps()
            self.caps = caps.to_string() if caps else "?"
            self.log(f"first frame, caps: {self.caps}")
        now = time.monotonic()
        self.stamps.append(now)
        self.captured.append(now)
        return Gst.PadProbeReturn.OK

    def on_query(self, pad, info):
        query = info.get_query()
        if query.type != Gst.QueryType.LATENCY:
            return Gst.PadProbeReturn.OK
        # PyGObject holds a second reference, which makes the query read-only; drop it for the write
        query.mini_object.refcount -= 1
        query.set_latency(True, 0, Gst.CLOCK_TIME_NONE)
        query.mini_object.refcount += 1
        return Gst.PadProbeReturn.HANDLED

    def on_mark(self, pad, info):
        # the encoder rewrites timestamps; with no B-frames frames leave in the order they entered
        if self.captured:
            self.stage.append(time.monotonic() - self.captured.pop(0))
        return Gst.PadProbeReturn.OK

    def on_error(self, bus, message):
        error, debug = message.parse_error()
        self.fail(f"pipeline error: {error.message} | {debug}")

    def finish(self):
        count = len(self.stamps)
        self.log(f"frames: {count}")
        if count > 1:
            gaps = sorted(b - a for a, b in zip(self.stamps, self.stamps[1:]))
            span = self.stamps[-1] - self.stamps[0]
            self.log(f"span {span:.2f}s, average {(count - 1) / span:.1f} fps")
            self.log("interval ms: min {:.1f} median {:.1f} p95 {:.1f} max {:.1f}".format(
                gaps[0] * 1000, gaps[len(gaps) // 2] * 1000,
                gaps[int(len(gaps) * 0.95)] * 1000, gaps[-1] * 1000))
        if self.stage:
            stage = sorted(self.stage)
            self.log("capture-to-mark ms ({} frames): min {:.1f} median {:.1f} p95 {:.1f} max {:.1f}".format(
                len(stage), stage[0] * 1000, stage[len(stage) // 2] * 1000,
                stage[int(len(stage) * 0.95)] * 1000, stage[-1] * 1000))
        self.loop.quit()
        return False

    def read_token(self):
        if self.args.token and os.path.exists(self.args.token):
            with open(self.args.token) as handle:
                return handle.read().strip()
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--token")
    parser.add_argument("--no-flag", action="store_true")
    parser.add_argument("--pipeline")
    parser.add_argument("--keepalive", type=int, default=0, help="pipewiresrc keepalive-time in ms")
    parser.add_argument("--by", choices=["path", "serial"], default="path")
    parser.add_argument("--own-connection", action="store_true")
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--source", help="GStreamer source used instead of the portal stream")
    args = parser.parse_args()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    Gst.init(None)
    return Probe(args).run()


if __name__ == "__main__":
    sys.exit(main())
