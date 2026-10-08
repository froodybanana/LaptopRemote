#!/usr/bin/env python3
"""Probe: what Hyprland's ext-data-control gives a client that wants to follow and set the clipboard.

Run on the laptop inside ~/laptopremote-probe after generating the protocol classes:
  python3 -m pywayland.scanner -i /usr/share/wayland/wayland.xml \
      /usr/share/wayland-protocols/staging/ext-data-control/ext-data-control-v1.xml -o wlclip
  python3 clipboard_probe.py
It replaces the laptop's clipboard with probe texts.
"""
import os
import select
import subprocess
import time

from pywayland.client import Display

from wlclip.ext_data_control_v1 import ExtDataControlManagerV1
from wlclip.wayland import WlSeat

started = time.monotonic()
readers = {}  # fd -> [label, bytearray]
writers = {}  # fd -> remaining bytes
offers = {}  # offer -> mime types


def log(*parts):
    print(f"{time.monotonic() - started:6.3f}", *parts, flush=True)


def pump(display, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        display.flush()
        ready_r, ready_w, _ = select.select([display.get_fd(), *readers], list(writers), [], 0.05)
        for fd in ready_r:
            if fd == display.get_fd():
                display.read()
                display.dispatch(block=False)
                continue
            label, data = readers[fd]
            chunk = os.read(fd, 65536)
            if chunk:
                data += chunk
            else:
                os.close(fd)
                del readers[fd]
                log(f"read {label}: {len(data)} bytes {bytes(data[:40])!r}")
        for fd in ready_w:
            try:
                sent = os.write(fd, writers[fd])
            except OSError as error:
                log("write failed", error)
                sent = len(writers[fd])
            writers[fd] = writers[fd][sent:]
            if not writers[fd]:
                os.close(fd)
                del writers[fd]
                log("write finished")
        display.dispatch(block=False)


def main():
    display = Display(os.environ.get("WAYLAND_DISPLAY", "wayland-1"))
    display.connect()
    found = {}
    registry = display.get_registry()
    registry.dispatcher["global"] = lambda registry, name, interface, version: found.__setitem__(interface, (name, version))
    display.roundtrip()
    log("manager", found.get("ext_data_control_manager_v1"), "seat", found.get("wl_seat"))
    seat = registry.bind(found["wl_seat"][0], WlSeat, 1)
    manager = registry.bind(found["ext_data_control_manager_v1"][0], ExtDataControlManagerV1, 1)
    device = manager.get_data_device(seat)

    def on_offer(device, offer):
        offers[offer] = []
        offer.dispatcher["offer"] = lambda offer, mime: offers[offer].append(mime)
        log("data_offer", type(offer).__name__)

    def on_selection(device, offer):
        if offer is None:
            log("selection: none")
            return
        mimes = offers.pop(offer, [])
        log("selection:", mimes[:8], f"({len(mimes)} types)")
        wanted = next((m for m in ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain") if m in mimes), None)
        if wanted:
            read_end, write_end = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            offer.receive(wanted, write_end)
            display.flush()
            os.close(write_end)
            readers[read_end] = [wanted, bytearray()]
        offer.destroy()

    def on_primary(device, offer):
        log("primary_selection", "none" if offer is None else "offer")
        if offer is not None:
            offers.pop(offer, None)
            offer.destroy()

    device.dispatcher["data_offer"] = on_offer
    device.dispatcher["selection"] = on_selection
    device.dispatcher["primary_selection"] = on_primary
    device.dispatcher["finished"] = lambda device: log("device finished")
    log("-- device made; what arrives unasked")
    pump(display, 0.5)

    def own(text):
        source = manager.create_data_source()
        for mime in ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING", "TEXT"):
            source.offer(mime)

        def on_send(source, mime, fd):
            log("send asked:", mime, "fd", fd, type(fd).__name__)
            os.set_blocking(fd, False)
            writers[fd] = text

        source.dispatcher["send"] = on_send
        source.dispatcher["cancelled"] = lambda source: log("source cancelled")
        device.set_selection(source)
        return source

    log("-- own a small selection")
    own(b"probe-small")
    pump(display, 0.5)
    log("-- wl-paste reads it")
    paste = subprocess.Popen(["wl-paste", "-n"], stdout=subprocess.PIPE)
    pump(display, 0.5)
    log("wl-paste gave", paste.communicate(timeout=2)[0])
    log("-- own 1 MiB")
    own(b"x" * (1024 * 1024))
    pump(display, 1.0)
    log("-- another program copies")
    subprocess.run(["wl-copy", "probe-other"], check=True)
    pump(display, 0.7)
    log("-- the same text is copied again by another program")
    subprocess.run(["wl-copy", "probe-other"], check=True)
    pump(display, 0.7)
    log("-- the clipboard is cleared")
    subprocess.run(["wl-copy", "--clear"], check=True)
    pump(display, 0.5)
    log("-- own again, then disconnect")
    own(b"probe-left-behind")
    pump(display, 0.5)
    display.disconnect()
    time.sleep(0.5)
    after = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=3)
    log("after disconnect wl-paste gives", after.stdout, after.stderr[:60])
    log("clipboard managers:", subprocess.run("pgrep -a -f 'wl-clip-persist|cliphist|clipse|walker'", shell=True,
                                              capture_output=True, text=True).stdout.strip() or "none")


if __name__ == "__main__":
    main()
