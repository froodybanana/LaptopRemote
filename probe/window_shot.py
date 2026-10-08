#!/usr/bin/env python3
"""Captures the LaptopRemote viewer window's own content, even when other windows cover it.

  window_shot.py OUT.png [--resize WxH]

Uses PrintWindow with PW_RENDERFULLCONTENT; a plain screen grab would show whatever is on top.
Prints the client size, the status text if the waiting label is showing, and a brightness spread.
"""
import argparse
import ctypes
import ctypes.wintypes as wt

from PIL import Image, ImageStat

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32


class BitmapInfo(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("width", wt.LONG), ("height", wt.LONG), ("planes", wt.WORD),
                ("bits", wt.WORD), ("compression", wt.DWORD), ("rest", wt.DWORD * 5)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--resize")
    args = parser.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    hwnd = user32.FindWindowW(None, "LaptopRemote")
    if not hwnd:
        print("no LaptopRemote window")
        return 1
    if args.resize:
        width, height = (int(n) for n in args.resize.split("x"))
        user32.SetWindowPos(hwnd, 0, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010)  # no move, no z-order, no activate
        return 0
    window, client = wt.RECT(), wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window))
    user32.GetClientRect(hwnd, ctypes.byref(client))
    width, height = window.right - window.left, window.bottom - window.top
    dc = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(dc)
    bitmap = gdi32.CreateCompatibleBitmap(dc, width, height)
    gdi32.SelectObject(memory, bitmap)
    user32.PrintWindow(hwnd, memory, 2)
    info = BitmapInfo(ctypes.sizeof(BitmapInfo), width, -height, 1, 32, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(hwnd, dc)
    image = Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, 1).convert("RGB")
    image.save(args.out)
    spread = ImageStat.Stat(image.crop((20, 60, width - 20, height - 20))).stddev
    print(f"client {client.right}x{client.bottom}, colour spread {[round(s) for s in spread]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
