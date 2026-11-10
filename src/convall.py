#!/usr/bin/env python3
"""ConvAll - convert anything, offline.

    ConvAll.exe                     open the app
    ConvAll.exe --selftest          check every conversion route
    ConvAll.exe a.png b.mp3 -t pdf  convert from the command line
    ConvAll.exe *.mp4 -t mp3 -o out

Options (same knobs as the app):
    --quality 60..96     image quality
    --resize 1080        cap image height
    --height 720         video/frame height
    --crf 23             video quality (lower = better)
    --bitrate 192k       audio bitrate
    --page a4|letter|fit PDF page size
    --orient auto|portrait|landscape
    --dpi 300            PDF render resolution
    --every 5            one frame every N seconds
"""
from __future__ import annotations

import ctypes
import sys

VERSION = "2.0"


def cli(argv: list[str]) -> int:
    from convall_engine import convert

    target = outdir = None
    files: list[str] = []
    opts: dict = {}
    # CLI equivalents of the options panel
    flags = {
        "--quality": ("quality", int), "--height": ("video_height", int),
        "--resize": ("max_h", int), "--page": ("pdf_page", str),
        "--orient": ("pdf_orient", str), "--dpi": ("pdf_dpi", int),
        "--bitrate": ("audio_bitrate", str), "--crf": ("video_crf", int),
        "--every": ("frame_every", int),
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-t", "--to") and i + 1 < len(argv):
            target = argv[i + 1]; i += 2
        elif a in ("-o", "--out") and i + 1 < len(argv):
            outdir = argv[i + 1]; i += 2
        elif a in flags and i + 1 < len(argv):
            key, conv = flags[a]
            raw = argv[i + 1]
            opts[key] = conv(raw) if conv is not str else raw
            if key == "video_height":
                opts["max_h"] = opts["video_height"]  # same knob, both sides
            i += 2
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a in ("-v", "--version"):
            print(f"ConvAll {VERSION}")
            return 0
        else:
            files.append(a); i += 1

    if not files:
        from convall_ui import run
        run()
        return 0
    if not target:  # files but no format: open the app preloaded
        from convall_ui import run
        run(files)
        return 0

    bad = 0
    for f in files:
        try:
            for o in convert(f, target, outdir, opts):
                print(o)
        except Exception as ex:
            print(f"{f}: {ex}", file=sys.stderr)
            bad = 1
    return bad


def _attach_console() -> None:
    """A --windowed exe has no stdout; borrow the caller's console for CLI use."""
    if sys.platform != "win32":
        return
    try:
        k32 = ctypes.windll.kernel32
        if k32.GetConsoleWindow():
            return
        if not k32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            return
        for stream, mode in (("stdout", "w"), ("stderr", "w")):
            try:
                setattr(sys, stream, open("CONOUT$", mode, encoding="utf-8",
                                          errors="replace", buffering=1))
            except Exception:
                pass
    except Exception:
        pass


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        _attach_console()
    if "--selftest" in argv:
        from convall_engine import selftest
        return selftest()
    return cli(argv[1:])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)