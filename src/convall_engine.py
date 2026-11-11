#!/usr/bin/env python3
"""ConvAll engine - every conversion route in one place, no network.

Images <-> images, images <-> pdf, pdf -> images/text, audio <-> audio,
audio <-> video, video -> images, tables (csv/tsv/json/xlsx/yaml) <-> tables.

Unknown extensions are sniffed with Pillow and ffprobe, so odd media files
still convert.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import io
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageOps
from convall_process import run as run_process
from convall_documents import FORMATS as DOCUMENT_FORMATS, read_text, write_text

# ------------------------------------------------------- optional extras ----

try:  # iPhone photos in, HEIC out
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAVE_HEIC = True
except Exception:
    HAVE_HEIC = False

try:
    import openpyxl

    HAVE_XLSX = True
except Exception:
    HAVE_XLSX = False

try:
    import yaml

    HAVE_YAML = True
except Exception:
    HAVE_YAML = False

Image.init()  # load all image plugins so the format table is complete


class ConvertError(Exception):
    pass


# --------------------------------------------------------------- formats ----

IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "avif", "gif", "bmp", "tif", "tiff",
             "ico", "tga", "dds", "jp2", "j2k", "qoi", "ppm", "pcx", "psd",
             "icns", "mpo", "heic", "heif", "apng", "dib", "pbm", "pgm", "pnm",
             "xbm", "sgi"}
AUDIO_EXT = {"mp3", "wav", "flac", "ogg", "oga", "m4a", "opus", "aac", "wma",
             "aiff", "aif", "ac3", "eac3", "amr", "ape", "wv", "mp2", "mka", "caf"}
VIDEO_EXT = {"mp4", "m4v", "mkv", "webm", "avi", "mov", "wmv", "flv", "mpg",
             "mpeg", "ts", "m2ts", "3gp", "ogv", "vob", "mts"}
TABLE_EXT = {"csv", "tsv", "json", "xlsx", "xlsm", "yaml", "yml", "jsonl", "ndjson", "xml"}
TEXT_EXT = {"txt", "md", "markdown", "log", "rst", "html", "htm", "docx", "odt", "epub", "fb2"}

# Pseudo-targets: things that aren't one-file-one-extension.
FRAME_TARGETS = {"png-frames", "jpg-frames"}
SPECIAL_LABEL = {"png-frames": "png frames", "jpg-frames": "jpg frames"}


def label_of(target: str) -> str:
    """Human text for a chip: usually the extension."""
    return SPECIAL_LABEL.get(target, target)

# Formats we offer as output, filtered by what this machine can actually write.
_IMG_CANDIDATES = ["png", "jpg", "webp", "avif", "gif", "bmp", "tif", "ico",
                   "tga", "dds", "jp2", "qoi", "ppm", "pcx", "heic", "svg",
                   "pdf", "pbm", "pgm", "sgi", "xbm", "icns"]
_IMG_SAVE = {
    "jpg": {"format": "JPEG", "quality": 92, "optimize": True},
    "webp": {"format": "WEBP", "quality": 88, "method": 4},
    "avif": {"format": "AVIF", "quality": 68},
    "gif": {"format": "GIF"},
    "tif": {"format": "TIFF", "compression": "tiff_lzw"},
    "ico": {"format": "ICO", "sizes": [(s, s) for s in (16, 32, 48, 64, 128, 256)]},
    "jp2": {"format": "JPEG2000", "quality_mode": "rates", "quality_layers": [4]},
    "qoi": {"format": "QOI"},
    "ppm": {"format": "PPM"},
    "pcx": {"format": "PCX"},
    "heic": {"format": "HEIF", "quality": 80},
    "bmp": {"format": "BMP"},
    "png": {"format": "PNG", "optimize": True},
    "pbm": {"format": "PPM"},
    "pgm": {"format": "PPM"},
    "sgi": {"format": "SGI"},
    "xbm": {"format": "XBM"},
    "icns": {"format": "ICNS"},
}

AUDIO_TARGETS = ["mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma",
                 "aiff", "ac3", "mp2", "eac3", "caf", "mka"]
AUDIO_ARGS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac", "-compression_level", "5"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wma": ["-c:a", "wmav2", "-b:a", "192k"],
    "aiff": ["-c:a", "pcm_s16be"],
    "ac3": ["-c:a", "ac3", "-b:a", "192k"],
    "mp2": ["-c:a", "mp2", "-b:a", "192k"],
    "eac3": ["-c:a", "eac3", "-b:a", "192k"],
    "caf": ["-c:a", "pcm_s16le"],
    "mka": ["-c:a", "flac"],
    "au": ["-c:a", "pcm_s16be"],
    "voc": ["-c:a", "pcm_u8"],
    "w64": ["-c:a", "pcm_s16le"],
    "alac": ["-c:a", "alac", "-f", "ipod"],
}

VIDEO_TARGETS = ["mp4", "mkv", "webm", "mov", "avi", "m4v", "wmv", "flv",
                 "mpg", "ts", "ogv", "3gp", "gif", "webp"]
_H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-pix_fmt", "yuv420p"]
VIDEO_ARGS = {
    "mp4": [*_H264, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    "m4v": [*_H264, "-c:a", "aac", "-b:a", "160k"],
    "mov": [*_H264, "-c:a", "aac", "-b:a", "160k"],
    "mkv": [*_H264, "-c:a", "aac", "-b:a", "160k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "libmp3lame", "-b:a", "192k"],
    "webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34",
             "-c:a", "libopus", "-b:a", "128k"],
    "wmv": ["-c:v", "wmv2", "-b:v", "2M", "-c:a", "wmav2", "-b:a", "192k"],
    "flv": ["-c:v", "flv", "-q:v", "5", "-c:a", "aac", "-b:a", "128k"],
    "mpg": ["-c:v", "mpeg2video", "-q:v", "5", "-c:a", "mp2", "-b:a", "192k"],
    "ts": [*_H264, "-c:a", "aac", "-b:a", "160k"],
    "nut": ["-c:v", "mpeg4", "-q:v", "5", "-c:a", "pcm_s16le"],
    "mpeg": ["-c:v", "mpeg2video", "-q:v", "5", "-c:a", "mp2", "-b:a", "192k"],
    "ogv": ["-c:v", "libtheora", "-q:v", "7", "-c:a", "libvorbis", "-q:a", "5"],
    "3gp": ["-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
            "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-ar", "44100", "-ac", "1"],
    "webp": ["-c:v", "libwebp", "-lossless", "0", "-q:v", "70", "-loop", "0"],
}
GIF_VF = ("fps=12,scale=560:-1:flags=lanczos,split[a][b];"
          "[a]palettegen[p];[b][p]paletteuse")
AUDIO_TARGETS += ['au', 'voc', 'w64', 'alac']
AUDIO_EXT.update(AUDIO_TARGETS)
VIDEO_TARGETS += ['nut', 'mpeg']
VIDEO_EXT.update(VIDEO_TARGETS)

# --------------------------------------------------------------- options ----
# One table drives both the UI and the converters, so a knob can never appear
# on screen without doing something.
PAGE_SIZES = {"a4": (794, 1123), "letter": (816, 1056)}   # 96 dpi

OPTIONS: dict[str, dict] = {
    "quality": {
        "label": "QUALITY",
        "choices": [("Small", 60), ("Normal", 78), ("High", 88), ("Max", 96)],
        "default": 88,
        "hint": "image compression",
    },
    "max_h": {
        "label": "RESIZE",
        "choices": [("Source", 0), ("4K", 2160), ("1080", 1080),
                    ("720", 720), ("480", 480)],
        "default": 0,
        "hint": "cap the long side",
    },
    "pdf_page": {
        "label": "PAGE",
        "choices": [("Fit image", "fit"), ("A4", "a4"), ("Letter", "letter")],
        "default": "fit",
        "hint": "page size",
    },
    "pdf_orient": {
        "label": "ORIENTATION",
        "choices": [("Auto", "auto"), ("Portrait", "portrait"),
                    ("Landscape", "landscape")],
        "default": "auto",
        "hint": "",
    },
    "pdf_dpi": {
        "label": "RESOLUTION",
        "choices": [("72 dpi", 72), ("150 dpi", 150), ("300 dpi", 300)],
        "default": 150,
        "hint": "render quality",
    },
    "audio_bitrate": {
        "label": "BITRATE",
        "choices": [("96k", "96k"), ("128k", "128k"), ("192k", "192k"),
                    ("256k", "256k"), ("320k", "320k")],
        "default": "192k",
        "hint": "audio quality",
    },
    "video_height": {
        "label": "RESOLUTION",
        "choices": [("Source", 0), ("4K", 2160), ("1080", 1080),
                    ("720", 720), ("480", 480)],
        "default": 0,
        "hint": "output height",
    },
    "video_crf": {
        "label": "QUALITY",
        "choices": [("Best", 18), ("High", 23), ("Balanced", 28),
                    ("Small", 32)],
        "default": 23,
        "hint": "lower is better",
    },
    "frame_every": {
        "label": "FRAMES",
        "choices": [("1/sec", 1), ("1/2 sec", 2), ("1/5 sec", 5),
                    ("1/10 sec", 10)],
        "default": 1,
        "hint": "spacing",
    },
}
OPTIONS.update({
    'sample_rate': {'label': 'SAMPLE RATE', 'choices': [('Source', 0), ('44.1k', 44100), ('48k', 48000)], 'default': 0},
    'channels': {'label': 'CHANNELS', 'choices': [('Source', 0), ('Mono', 1), ('Stereo', 2)], 'default': 0},
    'fps': {'label': 'FPS CAP', 'choices': [('Source', 0), ('24', 24), ('30', 30), ('60', 60)], 'default': 0},
    'strip_metadata': {'label': 'METADATA', 'choices': [('Keep', False), ('Remove', True)], 'default': False},
})
TEXT_OPTIONS = {
    'output_name': 'File name', 'title': 'Title', 'author': 'Author / Artist',
    'album': 'Album', 'comment': 'Comment', 'copyright': 'Copyright',
    'date': 'Year / Date', 'genre': 'Genre',
}
TAG_FORMATS = {'mp3', 'm4a', 'flac', 'ogg', 'opus', 'mka', 'mkv', 'mp4', 'mov', 'wma', 'webm'}


def metadata_fields(target):
    if target in TAG_FORMATS:
        return list(TEXT_OPTIONS)
    if target == 'pdf':
        return ['output_name', 'title', 'author', 'comment', 'copyright']
    return ['output_name']

_LOSSLESS_AUDIO = {"wav", "flac", "aiff", "ac3", "caf", "mka"}
_STILL_IMAGE_TARGETS = {"png", "jpg", "webp", "avif", "gif", "bmp", "tif",
                        "ico", "tga", "dds", "jp2", "qoi", "ppm", "pcx", "heic"}


def options_for(target: str, source_kind: str = "") -> list[str]:
    """Which knobs make sense for this target, in display order."""
    t = target
    if t == "pdf":
        # images can be downscaled before they go in (keeps PDFs small);
        # a raster quality slider would be a lie, PIL writes PDFs losslessly
        return ["pdf_page", "pdf_orient"] + (
            ["max_h"] if source_kind == "image" else [])
    if t in FRAME_TARGETS:
        return ["frame_every", "quality"]
    if t in _STILL_IMAGE_TARGETS:
        keys = []
        if source_kind == "pdf":
            keys.append("pdf_dpi")
        else:
            keys.append("max_h")
        if t in ("jpg", "webp", "avif", "heic", "jp2"):
            keys.append("quality")
        return keys
    if t in AUDIO_ARGS:
        return ([] if t in _LOSSLESS_AUDIO or t in ('au', 'voc', 'w64', 'alac') else ["audio_bitrate"]) + ['sample_rate', 'channels', 'strip_metadata']
    if t in VIDEO_ARGS:
        if t in ("gif", "webp"):
            return ["video_height"]
        return ["video_height", "video_crf", "audio_bitrate", 'fps', 'sample_rate', 'channels', 'strip_metadata']
    if t == "svg":
        return ["max_h"]
    return []


def option_value(opts: dict, key: str):
    return (opts or {}).get(key, OPTIONS[key]["default"])


_height_cache: dict[tuple, int | None] = {}


def source_height(path) -> int | None:
    """Read source dimensions once; never infer resolution from its suffix."""
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _height_cache:
        height = None
        try:
            if kind_of(path) == "image":
                with Image.open(path) as im:
                    height = ImageOps.exif_transpose(im).height
            elif kind_of(path) == "video":
                r = run_process(
                    [ffprobe(), "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
                    capture_output=True, text=True, timeout=15)
                height = int(r.stdout.strip().splitlines()[0])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired, ConvertError):
            pass
        _height_cache[key] = height
    return _height_cache[key]


def image_targets() -> list[str]:
    ext = set(Image.EXTENSION)
    save = set(Image.SAVE)
    out = []
    for t in _IMG_CANDIDATES:
        if t in ("pdf", "svg"):
            out.append(t)
        elif t == "heic":
            if HAVE_HEIC:
                out.append(t)
        elif f".{t}" in ext and Image.EXTENSION[f".{t}"] in save:
            out.append(t)
    return out


def table_targets() -> list[str]:
    out = ["csv", "tsv", "json", "jsonl", "xml"]
    if HAVE_XLSX:
        out.append("xlsx")
    if HAVE_YAML:
        out.append("yaml")
    return out


GROUP_ORDER = ["images", "docs", "audio", "video"]


def group_of(fmt: str) -> str:
    if fmt in DOCUMENT_FORMATS:
        return 'docs'
    if fmt in ("pdf", "txt", "mp3-speech", "svg") or fmt in TABLE_EXT:
        return "docs"
    if fmt in AUDIO_EXT:
        return "audio"
    return "images" if fmt in IMAGE_EXT else "video"


# --------------------------------------------------------------- helpers ----

def ext_of(p) -> str:
    return Path(p).suffix.lower().lstrip(".")


def app_dir() -> Path:
    """Folder the app lives in (works for script and frozen exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


FFMPEG_URLS = (
    # GitHub's mirror is ~6x faster here than gyan.dev; gyan is the fallback.
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
)


def ffmpeg_dir() -> Path:
    """Where a downloaded ffmpeg lands: next to the app."""
    return app_dir()


def download_ffmpeg(progress=None) -> Path:
    """Fetch a static ffmpeg build and drop ffmpeg.exe + ffprobe.exe beside us.

    Only ever called because the user clicked the button; nothing else in
    ConvAll touches the network. Returns the exe path.
    """
    import tempfile
    import urllib.request
    import zipfile

    target = ffmpeg_dir()
    target.mkdir(parents=True, exist_ok=True)
    last = "no download attempted"
    for url in FFMPEG_URLS:
        tmp = Path(tempfile.mkdtemp()) / "ff.zip"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ConvAll"})
            with urllib.request.urlopen(req, timeout=90) as r, tmp.open("wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
            with zipfile.ZipFile(tmp) as z:
                wanted = [n for n in z.namelist()
                          if n.lower().endswith(("ffmpeg.exe", "ffprobe.exe"))
                          and "/bin/" in n.replace("\\", "/")]
                if not wanted:
                    raise ConvertError("archive had no ffmpeg.exe")
                for name in wanted:
                    data = z.read(name)
                    dest = target / Path(name).name
                    dest.write_bytes(data)
            exe = target / "ffmpeg.exe"
            if not exe.exists():
                raise ConvertError("download finished but ffmpeg.exe is missing")
            os.environ["FFMPEG"] = str(exe)
            return exe
        except Exception as ex:
            last = f"{type(ex).__name__}: {ex}"
            continue
    raise ConvertError(f"couldn't download ffmpeg ({last})")


def ffmpeg() -> str:
    found = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if found and Path(found).exists():
        return found
    here = app_dir()
    for guess in (here / "ffmpeg.exe", here / "bin" / "ffmpeg.exe",
                  Path.cwd() / "ffmpeg.exe",
                  r"C:\ffmpeg\bin\ffmpeg.exe",
                  "/usr/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"):
        if Path(guess).exists():
            return str(guess)
    raise ConvertError(
        "ffmpeg not found - put ffmpeg.exe next to ConvAll.exe "
        f"(in {here}) to unlock audio, video and gif")


def ffprobe() -> str:
    exe = ffmpeg()
    for name in ("ffprobe", "ffprobe.exe"):
        cand = Path(exe).with_name(name)
        if cand.exists():
            return str(cand)
    found = shutil.which("ffprobe")
    if found:
        return found
    raise ConvertError("ffprobe missing next to ffmpeg")


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    n = 1
    while (cand := p.with_name(f"{p.stem} ({n}){p.suffix}")).exists():
        n += 1
    return cand


def run(cmd: list[str]) -> None:
    r = run_process(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        tail = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()][-3:]
        raise ConvertError("ffmpeg: " + " | ".join(tail))


_kind_cache: dict[str, str] = {}


def _sniff(p: Path) -> str:
    """Guess the real type when the extension is not one we know."""
    try:
        with Image.open(p) as im:
            im.verify()
        return "image"
    except Exception:
        pass
    try:
        r = run_process([ffprobe(), "-v", "error", "-show_entries",
                            "stream=codec_type:stream_disposition=attached_pic",
                            "-of", "json", str(p)],
                           capture_output=True, text=True, timeout=25)
        streams = json.loads(r.stdout or "{}").get("streams", [])
        kinds = [s.get("codec_type") for s in streams]
        video = [s for s in streams if s.get("codec_type") == "video"
                 and s.get("disposition", {}).get("attached_pic") != 1]
        if video:
            return "video"
        if "audio" in kinds:
            return "audio"
        if "video" in kinds:
            return "video"
    except Exception:
        pass
    return "?"


def kind_of(p) -> str:
    p = Path(p)
    key = str(p)
    if key in _kind_cache:
        return _kind_cache[key]
    e = ext_of(p)
    if e == "pdf":
        k = "pdf"
    elif e in IMAGE_EXT:
        k = "image"
    elif e in AUDIO_EXT:
        k = "audio"
    elif e in VIDEO_EXT:
        k = "video"
    elif e in TABLE_EXT:
        k = "table"
    elif e in TEXT_EXT:
        k = "text"
    else:
        k = _sniff(p)
    _kind_cache[key] = k
    return k


def direct_targets(p) -> list[str]:
    k = kind_of(p)
    if k == "image":
        return [t for t in image_targets() if t != ext_of(p)] + ['mp4', 'webm', 'mkv']
    if k == "pdf":
        return ["png", "jpg", "webp", *DOCUMENT_FORMATS]
    if k == "audio":
        return ([t for t in AUDIO_TARGETS if t != ext_of(p)] +
                [t for t in ("mp4", "mkv", "webm", "ogv") if t != ext_of(p)] +
                ["png", "jpg"])
    if k == "video":
        return ([t for t in VIDEO_TARGETS if t != ext_of(p)] +
                [t for t in AUDIO_TARGETS if t != ext_of(p)] +
                ["png", "jpg", "pdf", "png-frames", "jpg-frames"])
    if k == "table":
        return [t for t in table_targets() if t != ext_of(p)] + list(DOCUMENT_FORMATS) + ['pdf']
    if k == "text":
        return [t for t in (*DOCUMENT_FORMATS, "pdf", "mp3", "wav") if t != ext_of(p)]
    return []


def conversion_route(source, target):
    """Shortest useful route, at most three conversions, no byte reinterpretation.

    Only semantic bridges are explored: PDF pages/images, waveform pictures,
    text and speech. Tables never become fake images of raw binary data.
    """
    from collections import deque
    if target == ext_of(source) and kind_of(source) in ('image', 'audio', 'video', 'table', 'text'):
        return [target]
    todo = deque([(Path(source), [])])
    visited = {ext_of(source)}
    bridges = {'pdf', 'png', 'txt', 'wav'}
    while todo:
        current, route = todo.popleft()
        targets = direct_targets(current)
        if route and kind_of(current) == 'pdf' and kind_of(source) not in ('pdf', 'text', 'table'):
            targets = [fmt for fmt in targets if fmt != 'txt']
        if target in targets:
            return route + [target]
        if len(route) >= 2:
            continue
        for fmt in targets:
            if fmt in bridges and fmt not in visited:
                visited.add(fmt)
                todo.append((Path('intermediate.' + fmt), route + [fmt]))
    return []


def targets_for(p):
    candidates = list(dict.fromkeys(direct_targets(p) + image_targets() +
                      list(DOCUMENT_FORMATS) + AUDIO_TARGETS + VIDEO_TARGETS))
    return [t for t in candidates if t != ext_of(p) and conversion_route(p, t)]


def targets_for_many(files) -> list[str]:
    seen: list[str] = []
    for f in files:
        for t in targets_for(f):
            if t not in seen:
                seen.append(t)
    return seen


def targets_for_all(files) -> list[str]:
    """Formats that work for *every* file - what a chip should offer."""
    files = list(files)
    if not files:
        return []
    sets = [targets_for(f) for f in files]
    common = set(sets[0])
    for s in sets[1:]:
        common &= set(s)
    if not common:                     # mixed selection: fall back to union
        common = set(targets_for_many(files))
    order = []
    for f in files[:1]:
        order = targets_for(f)
    ordered = [t for t in order if t in common]
    ordered += sorted(t for t in common if t not in ordered)
    return ordered


def targets_grouped(files) -> dict[str, list[str]]:
    files = list(files)
    groups: dict[str, list[str]] = {}
    for t in targets_for_all(files):
        groups.setdefault(group_of(t), []).append(t)
    if {kind_of(f) for f in files} == {"video"}:
        # gif/webp are animations when the sources are videos, not stills
        for t in ("gif", "webp"):
            if t in groups.get("images", []):
                groups["images"].remove(t)
                groups.setdefault("video", []).append(t)
                groups["video"].sort()
    if "images" in groups and not groups["images"]:
        del groups["images"]
    return {g: sorted(groups[g]) for g in GROUP_ORDER if g in groups}


# ------------------------------------------------------------- converters ----

def _flatten(img: Image.Image, bg="white") -> Image.Image:
    """Drop alpha onto a solid colour so JPEG/PDF don't come out black."""
    if img.mode in ("RGBA", "LA", "P", "PA") or \
            (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        base = Image.new("RGBA", img.size, bg)
        base.alpha_composite(img)
        return base.convert("RGB")
    if img.mode not in ("RGB", "L"):
        return img.convert("RGB")
    return img


def _fit_to_page(img: Image.Image, page: str, orient: str, margin=36):
    """Place an image on a fixed page, scaled to fit, centred, white margins."""
    pw, ph = PAGE_SIZES[page]
    landscape = (orient == "landscape") or (
        orient == "auto" and img.width > img.height)
    if landscape:
        pw, ph = max(pw, ph), min(pw, ph)
    box_w, box_h = pw - 2 * margin, ph - 2 * margin
    scale = min(box_w / img.width, box_h / img.height)
    if scale != 1:
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.LANCZOS)
    sheet = Image.new("RGB", (pw, ph), "white")
    sheet.paste(img, ((pw - img.width) // 2, (ph - img.height) // 2))
    return sheet


def _downscale(img: Image.Image, max_h) -> Image.Image:
    max_h = int(max_h or 0)
    if max_h and img.height > max_h:
        w = max(1, round(img.width * max_h / img.height))
        return img.resize((w, max_h), Image.LANCZOS)
    return img


def convert_image(src: Path, target: str, outdir: Path, opts: dict | None = None):
    opts = opts or {}
    out = unique_path(outdir / f"{src.stem}.{target}")
    with Image.open(src) as im:
        im.load()
        im = ImageOps.exif_transpose(im)  # phone photos upright
        im = _downscale(im, option_value(opts, "max_h"))
        if target == "pdf":
            sheet = _flatten(im)
            page = option_value(opts, "pdf_page")
            if page in PAGE_SIZES:
                sheet = _fit_to_page(sheet, page,
                                     option_value(opts, "pdf_orient"))
            sheet.save(out, "PDF", resolution=96.0)
            return [out]
        elif target == "svg":  # a real SVG that embeds the raster
            import base64
            import io

            buf = io.BytesIO()
            im.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            out.write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{im.width}" height="{im.height}" '
                f'viewBox="0 0 {im.width} {im.height}">'
                f'<image width="{im.width}" height="{im.height}" '
                f'href="data:image/png;base64,{b64}"/></svg>',
                encoding="utf-8")
            return [out]
        kwargs = dict(_IMG_SAVE.get(target, {}))
        if "quality" in kwargs:
            kwargs["quality"] = int(option_value(opts, "quality"))
        fmt = kwargs.pop("format", None)
        if target in ("pbm", "xbm"):
            im = im.convert("1")
        elif target == "pgm":
            im = im.convert("L")
        elif target in ("sgi", "icns"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        if target in ("jpg", "ico") or fmt in ("JPEG", "ICO", "BMP", "PPM", "PCX"):
            im = _flatten(im)
        elif fmt in ("GIF",):
            im = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
        try:
            im.save(out, fmt, **kwargs)
        except (OSError, ValueError, KeyError) as ex:
            raise ConvertError(f"can't write .{target}: {ex}") from ex
    return [out]


def convert_pdf(src: Path, target: str, outdir: Path,
                opts: dict | None = None) -> list[Path]:
    import pypdfium2 as pdfium

    opts = opts or {}
    scale = max(0.25, float(option_value(opts, "pdf_dpi")) / 72.0)
    doc = pdfium.PdfDocument(str(src))
    made: list[Path] = []
    try:
        if target == "txt":
            parts = []
            for i in range(len(doc)):
                page = doc[i]
                parts.append(page.get_textpage().get_text_range())
                page.close()
            body = "\n".join(parts).strip()
            if not body:
                raise ConvertError("pdf has no text layer (scanned?) - try pdf -> png")
            out = unique_path(outdir / f"{src.stem}.txt")
            out.write_text(body, encoding="utf-8")
            return [out]
        for i in range(len(doc)):
            page = doc[i]
            pil = page.render(scale=scale).to_pil()
            page.close()
            suffix = "" if len(doc) == 1 else f"_p{i + 1:03d}"
            out = unique_path(outdir / f"{src.stem}{suffix}.{target}")
            kwargs = dict(_IMG_SAVE.get(target, {}))
            if "quality" in kwargs:
                kwargs["quality"] = int(option_value(opts, "quality"))
            fmt = kwargs.pop("format", None)
            if target == "jpg":
                _flatten(pil).save(out, "JPEG", quality=kwargs.get("quality", 92))
            else:
                pil.save(out, fmt, **kwargs)
            made.append(out)
    finally:
        doc.close()
    return made


def _patched(args: list[str], flag: str, value) -> list[str]:
    """Replace the value after a flag, or append the pair if it's absent."""
    out = list(args)
    if flag in out:
        i = out.index(flag)
        if i + 1 < len(out):
            out[i + 1] = str(value)
        else:
            out.append(str(value))
    else:
        out += [flag, str(value)]
    return out


def _extra_media_args(target, opts):
    args = []
    for key, flag in (('sample_rate', '-ar'), ('channels', '-ac')):
        if option_value(opts, key):
            args += [flag, str(option_value(opts, key))]
    if option_value(opts, 'strip_metadata'):
        args += ['-map_metadata', '-1']
    if target in TAG_FORMATS:
        for key in metadata_fields(target):
            if key != 'output_name' and opts.get(key):
                tag = 'artist' if key == 'author' else key
                args += ['-metadata', f'{tag}={opts[key]}']
    return args


def _media_args(target: str, kind: str, opts: dict) -> list[str]:
    """Build ffmpeg args for target, honouring bitrate/resolution/quality."""
    if target in AUDIO_ARGS:
        args = list(AUDIO_ARGS[target])
        br = option_value(opts, "audio_bitrate")
        if "-b:a" in args:
            args = _patched(args, "-b:a", br)
        elif "-q:a" in args:            # vorbis: map bitrate to quality
            step = {"96k": "3", "128k": "4", "192k": "5",
                    "256k": "7", "320k": "9"}.get(br, "5")
            args = _patched(args, "-q:a", step)
        return args + _extra_media_args(target, opts)

    args = list(VIDEO_ARGS[target])
    crf = int(option_value(opts, "video_crf"))
    height = int(option_value(opts, "video_height"))
    if "-crf" in args:
        args = _patched(args, "-crf", crf)
    elif "-q:v" in args:                # codecs without CRF
        args = _patched(args, "-q:v",
                        max(1, min(10, round(1 + (crf - 16) * 0.4))))
    if "-b:a" in args:
        args = _patched(args, "-b:a", option_value(opts, "audio_bitrate"))
    if height:
        args += ["-vf", f"scale=w='min(iw,iw*{height}/ih)':h='min(ih,{height})':force_divisible_by=2:force_original_aspect_ratio=decrease"]
    fps = option_value(opts, 'fps')
    if fps:
        # ffmpeg's fps filter duplicates frames; instead cap output rate.
        args += ['-fpsmax', str(fps)]
    return args + _extra_media_args(target, opts)


def _gif_filter(opts: dict) -> str:
    height = int(option_value(opts, "video_height")) or 480
    return (f"fps=12,scale=w='min(iw,iw*{height}/ih)':h='min(ih,{height})':flags=lanczos,split[a][b];"
            f"[a]palettegen[p];[b][p]paletteuse")


def convert_media(src: Path, target: str, outdir: Path,
                  opts: dict | None = None) -> list[Path]:
    opts = opts or {}
    exe, kind = ffmpeg(), kind_of(src)

    if target in FRAME_TARGETS:                       # every N seconds -> images
        return _video_frames(src, target.split("-")[0], outdir, opts)

    out = unique_path(outdir / f"{src.stem}.{target}")

    if target == "pdf":                               # contact sheet
        return _video_pdf(src, outdir, opts)
    if target in ("png", "jpg"):
        if kind == "audio":                           # waveform picture
            return _audio_image(src, target, outdir)
        for ss in ("1", "0"):                         # grab a frame
            run([exe, "-y", "-ss", ss, "-i", str(src), "-frames:v", "1",
                 "-q:v", "2", str(out)])
            if out.exists() and out.stat().st_size:
                return [out]
        raise ConvertError("couldn't grab a frame")
    if target in AUDIO_ARGS:                            # strip video
        run([exe, "-y", "-i", str(src), "-vn",
             *_media_args(target, kind, opts), str(out)])
    elif target == "gif":
        run([exe, "-y", "-i", str(src), "-vf", _gif_filter(opts),
             "-loop", "0", str(out)])
    elif target in VIDEO_ARGS:
        args = _media_args(target, kind, opts)
        if kind == "audio":                             # audio -> video still
            h = int(option_value(opts, "video_height")) or 720
            w = 1280 if h >= 720 else max(2, round(h * 16 / 9 / 2) * 2)
            run([exe, "-y", "-f", "lavfi", "-i",
                 f"color=c=0x10141b:s={w}x{h}:r=30", "-i", str(src),
                 "-shortest", *args, str(out)])
        elif target == "3gp":
            run([exe, "-y", "-i", str(src), "-vf",
                 "scale=176:144:force_original_aspect_ratio=decrease,"
                 "pad=176:144:(ow-iw)/2:(oh-ih)/2:color=black",
                 *args, str(out)])
        else:
            run([exe, "-y", "-i", str(src), *args, str(out)])
    else:
        raise ConvertError(f"no media route to .{target}")
    return [out]


def _video_frames(src: Path, fmt: str, outdir: Path,
                  opts: dict | None = None) -> list[Path]:
    """One image every N seconds of video, capped so a film can't fill the disk."""
    exe = ffmpeg()
    every = max(1, int(option_value(opts or {}, "frame_every")))
    stem = unique_path(outdir / f"{src.stem}_frame.png").with_suffix("")
    pattern = f"{stem}_%04d.{fmt}"
    run([exe, "-y", "-i", str(src), "-vf", f"fps=1/{every}",
         "-frames:v", "240", "-q:v", "3", pattern])
    made = sorted(outdir.glob(f"{stem.name}_*.{fmt}"))
    if not made:
        raise ConvertError("no frames produced")
    return made


def _video_pdf(src: Path, outdir: Path, opts: dict | None = None) -> list[Path]:
    """Every Nth second of video as thumbnails on PDF pages."""
    import tempfile

    frames = _video_frames(src, "jpg", Path(tempfile.mkdtemp()), opts)
    try:
        cols, rows = 4, 3
        cw, ch, gap, pad = 400, 225, 16, 36
        pw = cols * cw + (cols + 1) * gap
        from PIL import ImageDraw

        pages = []
        per = cols * rows
        for start in range(0, len(frames), per):
            batch = frames[start:start + per]
            used = max(1, -(-len(batch) // cols))   # only as tall as needed
            ph = used * ch + (used + 1) * gap + 40
            page = Image.new("RGB", (pw, ph), "white")
            d = ImageDraw.Draw(page)
            d.text((gap, gap), f"{src.name} — frames "
                               f"{start + 1}-{min(start + per, len(frames))}",
                   fill="#444444")
            for i, f in enumerate(batch):
                c, r = i % cols, i // cols
                x = gap + c * (cw + gap)
                y = gap + 20 + r * (ch + gap)
                with Image.open(f) as im:
                    page.paste(im.convert("RGB").resize((cw, ch), Image.LANCZOS),
                               (x, y))
            pages.append(page)
        out = unique_path(outdir / f"{src.stem}.pdf")
        pages[0].save(out, "PDF", resolution=96.0, save_all=True,
                      append_images=pages[1:])
        return [out]
    finally:
        import shutil as _sh

        _sh.rmtree(Path(frames[0]).parent, ignore_errors=True)


def _audio_image(src: Path, target: str, outdir: Path) -> list[Path]:
    """Draw the waveform (or spectrum) of an audio file as a picture."""
    exe = ffmpeg()
    png = unique_path(outdir / f"{src.stem}.png")
    run([exe, "-y", "-i", str(src), "-filter_complex",
         "showwavespic=s=1600x600:colors=#3f7cff:scale=sqrt", "-frames:v", "1",
         str(png)])
    if target == "png":
        return [png]
    from PIL import Image as _I

    jpg = png.with_suffix(".jpg")
    with _I.open(png) as im:
        _I.new("RGB", im.size, "black").convert("RGB")
        base = _I.new("RGB", im.size, "#0b0e13")
        base.paste(im.convert("RGB"), (0, 0), im.convert("RGBA")
                   if im.mode in ("RGBA", "P") else None)
        base.save(jpg, "JPEG", quality=92)
    png.unlink(missing_ok=True)
    return [jpg]


def _rows_from(src: Path) -> list[dict]:
    e = ext_of(src)
    if e in ("csv", "tsv"):
        delim = "\t" if e == "tsv" else ","
        text = src.read_text(encoding="utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    elif e in ("jsonl", "ndjson"):
        rows = [json.loads(line) for line in src.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()]
    elif e == "xml":
        text = src.read_text(encoding="utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ConvertError("XML document types and entities are not supported")
        root = ET.fromstring(text)
        if root.tag != "rows" or any(row.tag != "row" for row in root):
            raise ConvertError("XML tables must use <rows><row>...</row></rows>")
        rows = [{cell.get("name", cell.tag): cell.text or "" for cell in row}
                for row in root]
    elif e == "json":
        data = json.loads(src.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else [data]
    elif e in ("yaml", "yml"):
        if not HAVE_YAML:
            raise ConvertError("yaml support needs pyyaml: pip install pyyaml")
        data = yaml.safe_load(src.read_text(encoding="utf-8-sig"))
        rows = data if isinstance(data, list) else [data]
    elif e in ("xlsx", "xlsm"):
        if not HAVE_XLSX:
            raise ConvertError("xlsx support needs openpyxl: pip install openpyxl")
        wb = openpyxl.load_workbook(str(src), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        head = [str(c) if c is not None else f"col{i}" for i, c in
                enumerate(next(it, []))]
        rows = [dict(zip(head, r)) for r in it]
        wb.close()
    else:
        raise ConvertError(f".{e} isn't a table")
    if not all(isinstance(r, dict) for r in rows):
        raise ConvertError("table data must be rows of key/value pairs")
    return rows


def _columns(rows: list[dict]) -> list[str]:
    return list(dict.fromkeys(k for r in rows for k in r))


def convert_text(src: Path, target: str, outdir: Path,
                 opts: dict | None = None) -> list[Path]:
    body = read_text(src)
    if not body.strip():
        raise ConvertError("file is empty")
    if target == "pdf":
        return [_text_pdf(src, body, outdir, opts)]
    if target in ("mp3", "wav"):
        return [_speak(src, body, target, outdir, opts)]
    raise ConvertError(f"no text route to .{target}")


def _font(size: int):
    from PIL import ImageFont

    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_pdf(src: Path, body: str, outdir: Path,
              opts: dict | None = None) -> Path:
    """Lay text out as pages at 96dpi, wrapping to the page width."""
    from PIL import ImageDraw

    opts = opts or {}
    page_key = option_value(opts, "pdf_page")
    page_key = page_key if page_key in PAGE_SIZES else "a4"
    W, H = PAGE_SIZES[page_key]
    if option_value(opts, "pdf_orient") == "landscape":
        W, H = H, W
    M = 64
    font, bold = _font(17), _font(24)
    pages, page = [], Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(page)
    y = M
    title = src.stem
    d.text((M, y), title[:70], fill="#111111", font=bold)
    y += 44
    d.line([(M, y), (W - M, y)], fill="#dddddd")
    y += 18
    for raw in body.replace("\t", "    ").splitlines():
        words, line = raw.split(), ""
        chunks = []
        while words:
            w = words.pop(0)
            cand = (line + " " + w).strip()
            if d.textlength(cand, font=font) <= W - 2 * M:
                line = cand
            else:
                if line:
                    chunks.append(line)
                line = w
        chunks.append(line)
        for chunk in chunks or [""]:
            if y > H - M - 24:
                pages.append(page)
                page = Image.new("RGB", (W, H), "white")
                d = ImageDraw.Draw(page)
                y = M
            d.text((M, y), chunk, fill="#1a1a1a", font=font)
            y += 26
    pages.append(page)
    out = unique_path(outdir / f"{src.stem}.pdf")
    pages[0].save(out, "PDF", resolution=96.0, save_all=True,
                  append_images=pages[1:])
    return out


def _speak(src: Path, body: str, target: str, outdir: Path,
           opts: dict | None = None) -> Path:
    """Read text aloud with the built-in Windows voice, save wav (then mp3)."""
    import subprocess as sp
    import tempfile

    opts = opts or {}
    wav = unique_path(outdir / f"{src.stem}.wav")
    tmp_txt = Path(tempfile.mkdtemp()) / "read.txt"
    tmp_txt.write_text(body[:60000], encoding="utf-8")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.Rate = 0;"
        f"$s.SetOutputToWaveFile('{wav}');"
        f"$s.Speak([IO.File]::ReadAllText('{tmp_txt}', [Text.Encoding]::UTF8));"
        "$s.Dispose()"
    )
    r = run_process(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
               capture_output=True, text=True)
    if not wav.exists() or wav.stat().st_size < 1000:
        raise ConvertError("text-to-speech failed: "
                           + (r.stderr or "no voice installed")[:120])
    if target == "wav":
        return wav
    mp3 = unique_path(outdir / f"{src.stem}.mp3")
    run([ffmpeg(), "-y", "-i", str(wav), *_media_args("mp3", "audio", opts),
         str(mp3)])
    wav.unlink(missing_ok=True)
    return mp3


def convert_table(src: Path, target: str, outdir: Path) -> list[Path]:
    rows = _rows_from(src)
    if not rows:
        raise ConvertError("table is empty")
    cols = _columns(rows)
    out = unique_path(outdir / f"{src.stem}.{target}")
    if target == "json":
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
    elif target == "jsonl":
        out.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n"
                               for row in rows), encoding="utf-8")
    elif target == "xml":
        root = ET.Element("rows")
        for row in rows:
            node = ET.SubElement(root, "row")
            for key, value in row.items():
                ET.SubElement(node, "cell", name=str(key)).text = (
                    "" if value is None else str(value))
        ET.indent(root)
        ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    elif target in ("csv", "tsv"):
        delim = "\t" if target == "tsv" else ","
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=delim,
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    elif target == "yaml":
        if not HAVE_YAML:
            raise ConvertError("yaml support needs pyyaml")
        out.write_text(yaml.safe_dump(rows, sort_keys=False,
                                      allow_unicode=True), encoding="utf-8")
    elif target == "xlsx":
        if not HAVE_XLSX:
            raise ConvertError("xlsx support needs openpyxl")
        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet("Sheet1")
        ws.append(cols)
        for r in rows:
            ws.append([r.get(c) for c in cols])
        wb.save(str(out))
    else:
        raise ConvertError(f"no table route to .{target}")
    return [out]


def convert_direct(src, target: str, outdir=None, opts: dict | None = None) -> list[Path]:
    src = Path(src)
    target = target.lower().lstrip(".")
    outdir = Path(outdir) if outdir else src.parent
    if not src.is_file():
        raise ConvertError(f"not a file: {src}")
    outdir.mkdir(parents=True, exist_ok=True)
    opts = dict(opts or {})
    k = kind_of(src)
    if k == "image":
        if target in image_targets():
            return convert_image(src, target, outdir, opts)
        if target in ('mp4', 'webm', 'mkv'):
            # Five-second still video. Original dimensions are never enlarged.
            import tempfile
            with tempfile.TemporaryDirectory() as temp:
                still = convert_image(src, 'png', Path(temp), opts)[0]
                output = unique_path(outdir / f'{src.stem}.{target}')
                args = _media_args(target, 'image', opts)
                # Crop odd dimensions down for encoders requiring even sizes.
                args = _patched(args, '-vf', "scale=w='max(2,trunc(iw/2)*2)':h='max(2,trunc(ih/2)*2)'")
                run([ffmpeg(), '-y', '-loop', '1', '-i', str(still), '-t', '5',
                     '-r', '24', *args, str(output)])
                return [output]
        raise ConvertError(f"can't make {label_of(target)} from an image")
    if k == "pdf":
        if target in ("png", "jpg", "webp", "txt"):
            return convert_pdf(src, target, outdir, opts)
        if target in DOCUMENT_FORMATS:
            import tempfile
            with tempfile.TemporaryDirectory(prefix='convall-text-') as temp:
                text = convert_pdf(src, 'txt', Path(temp), opts)[0]
                return write_text(read_text(text), unique_path(outdir / f'{src.stem}.{target}'))
        raise ConvertError(f"can't make {label_of(target)} from a pdf")
    if k in ("audio", "video"):
        return convert_media(src, target, outdir, opts)
    if k == "table":
        if target in table_targets():
            return convert_table(src, target, outdir)
        if target in DOCUMENT_FORMATS or target == 'pdf':
            rows = _rows_from(src)
            body = '\n'.join(' | '.join(f'{k}: {v}' for k, v in row.items()) for row in rows)
            if target == 'pdf':
                return [_text_pdf(src, body, outdir, opts)]
            return write_text(body, unique_path(outdir / f'{src.stem}.{target}'))
        raise ConvertError(f"can't make .{target} from a table")
    if k == "text":
        if target in DOCUMENT_FORMATS:
            return write_text(read_text(src), unique_path(outdir / f'{src.stem}.{target}'))
        if target in ("pdf", "mp3", "wav"):
            return convert_text(src, target, outdir, opts)
        raise ConvertError(f"can't make .{target} from text")
    raise ConvertError(f"don't know what .{ext_of(src)} is")


def _convert_outputs(src, target, outdir=None, opts=None):
    """Execute a planned route; discard intermediates, never overwrite originals."""
    import tempfile
    src = Path(src)
    if not src.is_file():
        raise ConvertError(f'not a file: {src}')
    target = target.lower().lstrip('.')
    name = str((opts or {}).get('output_name', '')).strip()
    if name and (name in ('.', '..') or any(c in name for c in '<>:"/\\|?*')
                 or name.endswith(('.', ' ')) or any(ord(c) < 32 for c in name)
                 or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                     *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}):
        raise ConvertError('Choose a valid Windows file name without path separators')
    route = conversion_route(src, target)
    if not route:
        raise ConvertError(f'No meaningful conversion route from .{ext_of(src)} to .{target}')
    destination = Path(outdir) if outdir else src.parent
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='convall-') as temp:
        current = [src]
        for step, fmt in enumerate(route):
            folder = destination if step == len(route) - 1 else Path(temp) / str(step)
            folder.mkdir(parents=True, exist_ok=True)
            current = [out for item in current
                       for out in convert_direct(item, fmt, folder, opts)]
        opts = opts or {}
        if target == 'pdf' and any(opts.get(k) for k in ('title', 'author', 'comment', 'copyright')):
            from pypdf import PdfReader, PdfWriter
            for output in current:
                writer = PdfWriter(clone_from=PdfReader(str(output)))
                tags = {}
                for key, tag in (('title', 'Title'), ('author', 'Author'), ('comment', 'Subject'), ('copyright', 'Keywords')):
                    if opts.get(key):
                        tags['/' + tag] = str(opts[key])
                writer.add_metadata(tags)
                updated = output.with_suffix('.metadata.pdf')
                writer.write(str(updated))
                writer.close()
                updated.replace(output)
        name = str(opts.get('output_name', '')).strip()
        if name:
            if name in ('.', '..') or any(c in name for c in '<>:"/\\|?*') or name.endswith(('.', ' ')):
                raise ConvertError('File name contains characters Windows cannot use')
            renamed = []
            for i, output in enumerate(current):
                dest = unique_path(destination / f'{name}{"_" + str(i+1) if len(current)>1 else ""}{output.suffix}')
                output.rename(dest)
                renamed.append(dest)
            current = renamed
        return current


def convert(src, target, outdir=None, opts=None):
    """Publish one result per source; bundle multi-file conversions as ZIP."""
    import tempfile
    import zipfile

    source = Path(src)
    destination = Path(outdir) if outdir else source.parent
    destination.mkdir(parents=True, exist_ok=True)
    # Stage beside the destination: publish atomically on the same filesystem.
    with tempfile.TemporaryDirectory(prefix='.convall-', dir=destination) as temp:
        staged = Path(temp)
        outputs = _convert_outputs(source, target, staged, opts)
        if len(outputs) == 1:
            final = unique_path(destination / outputs[0].name)
            outputs[0].replace(final)
            return [final]
        if not outputs:
            raise ConvertError('Conversion produced no files')
        name = str((opts or {}).get('output_name', '')).strip() or source.stem
        final = unique_path(destination / f'{name}_{target.lower().lstrip(".")}.zip')
        archive = staged / 'result.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for output in outputs:
                bundle.write(output, arcname=output.name)
        archive.replace(final)
        return [final]


# ---------------------------------------------------------------- selftest ----

def make_text_pdf(path) -> None:
    """Tiny valid one-page PDF with a real text layer (no deps needed)."""
    stream = b"BT /F1 24 Tf 72 700 Td (Hello ConvAll) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    Path(path).write_bytes(bytes(out))


def selftest(verbose=True) -> int:
    import tempfile

    ok, fail = 0, []

    def check(name, fn):
        nonlocal ok
        try:
            outs = fn()
            assert outs, f"{name}: no output"
            for o in outs:
                assert Path(o).is_file() and Path(o).stat().st_size > 0, \
                    f"{name}: empty output {o}"
            ok += 1
            if verbose:
                print(f"  ok   {name}")
        except Exception as ex:
            fail.append(f"{name}: {ex}")
            if verbose:
                print(f"  FAIL {name}: {ex}")

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        png = d / "a.png"
        Image.new("RGBA", (160, 100), (200, 40, 40, 128)).save(png)
        jpg = d / "b.jpg"
        Image.new("RGB", (64, 64), "navy").save(jpg)

        # images
        for t in [x for x in image_targets() if x not in ("pdf", "png")]:
            check(f"png->{t}", lambda t=t: convert(png, t, d))
        check("png->pdf", lambda: convert(png, "pdf", d))
        pdf = d / "a.pdf"
        check("jpg->png", lambda: convert(jpg, "png", d))
        for t in ("png", "jpg", "webp"):
            check(f"pdf->{t}", lambda t=t: convert(pdf, t, d))
        textpdf = d / "text.pdf"
        make_text_pdf(textpdf)
        check("pdf->txt", lambda: convert(textpdf, "txt", d))
        assert "ConvAll" in (d / "text.txt").read_text(encoding="utf-8")

        # tables
        csvf = d / "t.csv"
        csvf.write_text("name,n\nx,1\ny,2\n", encoding="utf-8")
        for t in table_targets():
            if t == "csv":
                continue
            check(f"csv->{t}", lambda t=t: convert(csvf, t, d))
        check("json->csv", lambda: convert(d / "t.json", "csv", d))
        if HAVE_XLSX:
            check("xlsx->json", lambda: convert(d / "t.xlsx", "json", d))
        if HAVE_YAML:
            check("yaml->csv", lambda: convert(d / "t.yaml", "csv", d))

        # text
        notes = d / "notes.md"
        notes.write_text("# Shopping\n\n" + ("milk and eggs. " * 60), encoding="utf-8")
        check("md->pdf", lambda: convert(notes, "pdf", d))
        check("md->wav", lambda: convert(notes, "wav", d))
        check("md->mp3", lambda: convert(notes, "mp3", d))

        # media
        try:
            exe = ffmpeg()
        except ConvertError:
            exe = None
            if verbose:
                print("  skip media (no ffmpeg)")
        if exe:
            wav = d / "tone.wav"
            run_process([exe, "-y", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1", str(wav)],
                           capture_output=True)
            for t in AUDIO_TARGETS:
                if t != "wav":
                    check(f"wav->{t}", lambda t=t: convert(wav, t, d))
            check("wav->mp4", lambda: convert(wav, "mp4", d))
            mp4 = d / "tone.mp4"
            for t in ("mp4", "mkv", "mov", "avi", "webm", "wmv", "flv", "mpg",
                      "ts", "ogv", "3gp", "gif", "webp", "png", "mp3"):
                check(f"mp4->{t}", lambda t=t: convert(mp4, t, d))
            check("mp4->pdf", lambda: convert(mp4, "pdf", d))
            check("mp4->png-frames", lambda: convert(mp4, "png-frames", d))
            check("mp4->jpg-frames", lambda: convert(mp4, "jpg-frames", d))
            check("mp3->png", lambda: convert(d / "tone.mp3", "png", d))
            check("mp3->jpg", lambda: convert(d / "tone.mp3", "jpg", d))

    if verbose:
        print(f"\n{ok} passed, {len(fail)} failed")
        for f in fail:
            print("  " + f)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
