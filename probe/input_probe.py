#!/usr/bin/env python3
"""Laptop side: does Hyprland take pointer and keyboard input from the virtual-device protocols?

  python3 -m pywayland.scanner -i /usr/share/wayland/wayland.xml ~/laptopremote/agent/protocols/*.xml -o ~/laptopremote-probe/wl
  python3 input_probe.py

Creates the headless output (the panel stays on), binds a virtual pointer to it, moves it and reads the
cursor back; presses Caps Lock on a virtual keyboard and reads the lock state back; watches the idle
notifier to see whether injected input counts as activity. Removes the output at the end.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path.home() / "laptopremote" / "agent"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from laptopremote_agent import hypr  # noqa: E402
from pywayland.client import Display  # noqa: E402
from pywayland.protocol.ext_idle_notify_v1 import ExtIdleNotifierV1  # noqa: E402
from wl.virtual_keyboard_unstable_v1 import ZwpVirtualKeyboardManagerV1  # noqa: E402
from wl.wayland import WlOutput, WlSeat  # noqa: E402
from wl.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1  # noqa: E402

OUTPUT = "LAPTOPREMOTE"
WIDTH, HEIGHT = 1600, 900


def now():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def keyboards():
    return {k["name"]: k for k in json.loads(hypr.command("j/devices"))["keyboards"]}


def main():
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-1")
    created = not hypr.output_exists(OUTPUT)
    if created:
        hypr.create_output(OUTPUT)
        hypr.set_mode(OUTPUT, WIDTH, HEIGHT, 1)
    display = Display()
    display.connect()
    try:
        found, outputs, names = {}, [], {}
        registry = display.get_registry()

        def on_global(registry, name, interface, version):
            if interface == "wl_output":
                output = registry.bind(name, WlOutput, min(version, 4))
                output.dispatcher["name"] = lambda output, text: names.__setitem__(text, output)
                outputs.append(output)
            else:
                found[interface] = (name, version)

        registry.dispatcher["global"] = on_global
        display.roundtrip()
        display.roundtrip()
        print("outputs:", sorted(names))
        seat = registry.bind(found["wl_seat"][0], WlSeat, 1)
        pointers = registry.bind(found["zwlr_virtual_pointer_manager_v1"][0], ZwlrVirtualPointerManagerV1, 2)
        keyboard_manager = registry.bind(found["zwp_virtual_keyboard_manager_v1"][0], ZwpVirtualKeyboardManagerV1, 1)

        idle = []
        notifier = registry.bind(found["ext_idle_notifier_v1"][0], ExtIdleNotifierV1, 1)
        notification = notifier.get_idle_notification(1500, seat)
        notification.dispatcher["idled"] = lambda n: idle.append("idled")
        notification.dispatcher["resumed"] = lambda n: idle.append("resumed")

        pointer = pointers.create_virtual_pointer_with_output(seat, names[OUTPUT])
        display.roundtrip()
        monitor = next(m for m in hypr.monitors() if m["name"] == OUTPUT)
        print("monitor at", monitor["x"], monitor["y"], monitor["width"], monitor["height"])
        for x, y in ((100, 200), (WIDTH - 1, HEIGHT - 1), (800, 450)):
            pointer.motion_absolute(now(), x, y, WIDTH, HEIGHT)
            pointer.frame()
            display.roundtrip()
            print(f"moved to {x},{y}: cursorpos {hypr.command('cursorpos').strip()}"
                  f" (expected {monitor['x'] + x}, {monitor['y'] + y})")

        time.sleep(2.5)
        display.roundtrip()
        print("after 2.5 s of nothing:", idle)
        pointer.motion_absolute(now(), 810, 460, WIDTH, HEIGHT)
        pointer.frame()
        display.roundtrip()
        time.sleep(0.2)
        display.roundtrip()
        print("after a pointer move:", idle)

        keymap = subprocess.run(["xkbcli", "compile-keymap", "--layout", "us"], check=True,
                                capture_output=True).stdout + b"\0"
        fd = os.memfd_create("keymap")
        os.write(fd, keymap)
        before = set(keyboards())
        keyboard = keyboard_manager.create_virtual_keyboard(seat)
        keyboard.keymap(1, fd, len(keymap))
        display.roundtrip()
        mine = (set(keyboards()) - before).pop()
        print("virtual keyboard:", mine, keyboards()[mine].get("active_keymap"))
        for press in (1, 2):
            for state in (1, 0):
                keyboard.key(now(), 58, state)  # KEY_CAPSLOCK
                display.roundtrip()
            time.sleep(0.1)
            print(f"caps lock pressed {press}x: capsLock={keyboards()[mine].get('capsLock')}")
        time.sleep(2.5)
        display.roundtrip()
        idle.clear()
        for state in (1, 0):
            keyboard.key(now(), 42, state)  # KEY_LEFTSHIFT
            display.roundtrip()
        time.sleep(0.2)
        display.roundtrip()
        print("after a key press:", idle)

        pointer.axis_source(0)
        pointer.axis_discrete(now(), 0, 15.0, 1)
        pointer.axis(now(), 1, 7.5)
        pointer.frame()
        pointer.button(now(), 0x112, 1)
        pointer.frame()
        pointer.button(now(), 0x112, 0)
        pointer.frame()
        display.roundtrip()
        print("wheel and middle button sent without a protocol error")
        keyboard.destroy()
        pointer.destroy()
        display.roundtrip()
    finally:
        display.disconnect()
        if created:
            hypr.remove_output(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
