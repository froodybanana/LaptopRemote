#!/usr/bin/env python3
"""PC side: checks the viewer's mouse path without giving the viewer the focus.

  viewer_mouse.py [X,Y] [--close]

Lists the windows inside the running viewer, says which window Windows would give a mouse message at
the middle of the video area, and posts a mouse move at X,Y (video-area pixels) to the video panel.
Compare with `hyprctl cursorpos` on the laptop. --close asks the viewer to close afterwards.
"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.FindWindowW.restype = wintypes.HWND
user32.ChildWindowFromPointEx.restype = wintypes.HWND
user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
CWP_SKIPINVISIBLE, CWP_SKIPDISABLED = 1, 2
WM_CLOSE, WM_MOUSEMOVE = 0x10, 0x200


def describe(window):
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(window), name, 256)
    rect = wintypes.RECT()
    user32.GetClientRect(wintypes.HWND(window), ctypes.byref(rect))
    return {"window": window, "parent": user32.GetParent(window), "class": name.value,
            "size": (rect.right, rect.bottom), "enabled": bool(user32.IsWindowEnabled(wintypes.HWND(window))),
            "visible": bool(user32.IsWindowVisible(wintypes.HWND(window)))}


def main():
    form = user32.FindWindowW(None, "LaptopRemote")
    if not form:
        print("no viewer window")
        return 1
    found = []
    user32.EnumChildWindows(wintypes.HWND(form), ENUM(lambda window, _: found.append(describe(window)) or True), 0)
    for entry in found:
        print(entry)
    parents = {entry["parent"] for entry in found}
    # the video panel is the visible child of the form that the sink has put a window into
    panels = [entry for entry in found if entry["parent"] == form and entry["window"] in parents]
    if not panels:
        print("no video panel with a sink window inside: is there a picture?")
        return 1
    panel = panels[0]
    width, height = panel["size"]
    middle = wintypes.POINT(width // 2, height // 2)
    hit = user32.ChildWindowFromPointEx(panel["window"], middle, CWP_SKIPINVISIBLE | CWP_SKIPDISABLED)
    print(f"video panel {panel['window']} {width}x{height}; a mouse message in its middle goes to {hit}"
          f" ({'the panel' if hit == panel['window'] else 'NOT the panel'})")
    positions = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    if positions:
        x, y = (int(n) for n in positions[0].split(","))
        user32.PostMessageW(panel["window"], WM_MOUSEMOVE, 0, (y << 16) | x)
        print(f"posted a mouse move at {x},{y}")
    if "--close" in sys.argv:
        user32.PostMessageW(form, WM_CLOSE, 0, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
