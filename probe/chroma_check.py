#!/usr/bin/env python3
"""Fetches the files chroma_probe.sh made on the laptop, decodes each in software and counts the
rows in the upper third of the last frame whose colour differs from the bars in the middle.

  chroma_check.py USER@LAPTOP

The test picture is colour bars moving sideways, so every row of the upper part is the same; a row
that is not shows what the encoder did to it. Needs Pillow and GStreamer with gst-libav.
"""
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile

from PIL import Image

GST = pathlib.Path(os.environ.get("GSTREAMER_1_0_ROOT_MSVC_X86_64")
                   or pathlib.Path(os.environ["LOCALAPPDATA"]) / "Programs/gstreamer/1.0/msvc_x86_64") / "bin"


def bad_rows(image):
    width, height = image.size
    columns = range(40, width, 97)
    reference = [image.getpixel((x, height // 2)) for x in columns]
    return [y for y in range(height // 3)
            if any(max(abs(a - b) for a, b in zip(image.getpixel((x, y)), wanted)) > 24
                   for x, wanted in zip(columns, reference))]


def main():
    laptop = sys.argv[1]
    work = pathlib.Path(tempfile.mkdtemp(prefix="chroma"))
    subprocess.run(["scp", "-q", f"{laptop}:/tmp/chroma.tar", str(work / "chroma.tar")], check=True)
    with tarfile.open(work / "chroma.tar") as tar:
        tar.extractall(work, filter="data")
    for stream in sorted(work.glob("*.h265")):
        frames = work / stream.stem
        frames.mkdir()
        subprocess.run([str(GST / "gst-launch-1.0.exe"), "-q", "filesrc", f"location={stream.as_posix()}",
                        "!", "h265parse", "!", "avdec_h265", "!", "videoconvert", "!", "video/x-raw,format=RGB",
                        "!", "pngenc", "compression-level=1",
                        "!", "multifilesink", f"location={frames.as_posix()}/%03d.png"],
                       stderr=subprocess.DEVNULL)
        pictures = sorted(frames.glob("*.png"))
        if not pictures:
            print(f"{stream.stem:10} no picture")
            continue
        rows = bad_rows(Image.open(pictures[-1]).convert("RGB"))
        print(f"{stream.stem:10} {stream.stat().st_size:9} bytes, {len(pictures)} frames, "
              f"{len(rows)} bad rows {rows[:1]}..{rows[-1:]}")


main()
