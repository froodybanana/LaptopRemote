#!/usr/bin/env python3
"""Laptop side: the agent's own injector against the real compositor, without a viewer.

  python3 -W ignore ~/laptopremote-probe/device_check.py

Creates the headless output (the panel stays on), moves the pointer, presses Caps Lock and holds Shift
and a button, then closes and removes the output.
"""
import json
import pathlib
import sys
import time

from gi.repository import GLib

sys.path.insert(0, str(pathlib.Path.home() / "laptopremote" / "agent"))
from laptopremote_agent import hypr, inject, wayland, xkb  # noqa: E402

OUTPUT = "LAPTOPREMOTE"


def virtual_keyboards():
    return [(k["name"], k["capsLock"], k["numLock"]) for k in json.loads(hypr.command("j/devices"))["keyboards"]
            if "virtual" in k["name"]]


def main():
    try:
        inject.open("NOSUCH", xkb.Keymap("us"))
    except wayland.InputError as error:
        print("refused:", error)
    hypr.create_output(OUTPUT)
    hypr.set_mode(OUTPUT, 1600, 900, 1)
    try:
        injector = inject.open(OUTPUT, xkb.Keymap("us"))
        monitor = next(m for m in hypr.monitors() if m["name"] == OUTPUT)
        injector.move(400, 300, 1600, 900)
        time.sleep(0.1)
        print("cursor", hypr.command("cursorpos").strip(), "output origin", monitor["x"], monitor["y"])
        injector.key(58, True)
        injector.key(58, False)
        injector.key(42, True)
        injector.button("left", True)
        injector.wheel(0.5, 1)
        time.sleep(0.1)
        print("keyboards (name, capsLock, numLock):", virtual_keyboards())
        context = GLib.MainContext.default()
        for _ in range(20):
            context.iteration(False)
        injector.close()
        print("after close:", virtual_keyboards())
    finally:
        hypr.remove_output(OUTPUT)


if __name__ == "__main__":
    main()
