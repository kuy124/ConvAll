"""Every option must measurably change the output, not just appear in the UI."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_engine as eng  # noqa: E402
from PIL import Image  # noqa: E402

S = ROOT / "tests" / "samples"
ff = eng.ffmpeg()


def probe(path, entries="format=duration") -> str:
    r = subprocess.run([eng.ffprobe(), "-v", "error",
                        "-show_entries", entries, "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""


def pdf_size(path) -> tuple[int, int]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        w, h = doc[0].get_size()
        return round(w), round(h)
    finally:
        doc.close()


def size(p):
    return Path(p).stat().st_size


with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    checks = []

    # ---- image quality: Max must be bigger than Small on the same source
    photo = d / "photo.png"
    im = Image.effect_mandelbrot((900, 600), (-2, -1, 1, 1), 60)
    im.convert("RGB").save(photo)
    small = eng.convert(photo, "jpg", d / "q1", {"quality": 60})[0]
    big = eng.convert(photo, "jpg", d / "q2", {"quality": 96})[0]
    checks.append(("image quality 60 vs 96", size(small), size(big),
                   size(big) > size(small) * 2))
    assert size(small) < size(big), "quality option ignored"

    # ---- image resize: 1080 cap
    tall = d / "tall.png"
    Image.new("RGB", (1200, 2400), "navy").save(tall)
    out = eng.convert(tall, "jpg", d / "r", {"max_h": 1080, "quality": 80})[0]
    h = Image.open(out).height
    checks.append(("image resize to 1080", h, 1080, h == 1080))
    assert h == 1080, f"resize ignored: {h}"
    src_h = Image.open(tall).height
    plain = eng.convert(tall, "jpg", d / "r2")[0]
    assert Image.open(plain).height == src_h, "default should keep the size"

    # ---- image -> pdf page size and orientation
    small_pdf = eng.convert(photo, "pdf", d / "p1", {"pdf_page": "fit"})[0]
    a4 = eng.convert(photo, "pdf", d / "p2", {"pdf_page": "a4"})[0]
    land = eng.convert(photo, "pdf", d / "p3",
                       {"pdf_page": "a4", "pdf_orient": "landscape"})[0]
    port = eng.convert(photo, "pdf", d / "p4",
                       {"pdf_page": "a4", "pdf_orient": "portrait"})[0]
    dims = pdf_size
    print(f"  pdf fit={dims(small_pdf)} a4/auto={dims(a4)} "
          f"a4/portrait={dims(port)}")
    assert dims(a4) != dims(small_pdf), "page size ignored"
    # auto picks landscape for a landscape photo; portrait must differ
    assert dims(port)[0] < dims(port)[1], "portrait is not portrait"
    assert dims(port) != dims(a4), "orientation ignored"
    checks.append(("pdf page a4", dims(a4), "595x842pt", True))

    # ---- pdf -> image dpi
    p72 = eng.convert(a4, "png", d / "d1", {"pdf_dpi": 72})[0]
    p300 = eng.convert(a4, "png", d / "d2", {"pdf_dpi": 300})[0]
    w72, w300 = Image.open(p72).width, Image.open(p300).width
    print(f"  pdf->png at 72dpi={w72}px, 300dpi={w300}px")
    assert w300 > w72 * 3, f"dpi ignored ({w72} vs {w300})"
    checks.append(("pdf render 72 vs 300 dpi", w72, w300, True))

    # image -> pdf honours the resize knob too (keeps big PDFs small)
    Image.new("RGB", (2000, 1500), "grey").save(d / "big.png")
    full_pdf = eng.convert(d / "big.png", "pdf", d / "pf")[0]
    small_pdf2 = eng.convert(d / "big.png", "pdf", d / "ps", {"max_h": 300})[0]
    print(f"  pdf from 2000px image: full={size(full_pdf)}B "
          f"max_h=300 -> {size(small_pdf2)}B")
    assert size(small_pdf2) < size(full_pdf) / 4, "max_h ignored for pdf"
    checks.append(("pdf from image, max_h 300", size(full_pdf),
                   size(small_pdf2), True))

    mp4 = S / "clip.mp4"

    # ---- video resolution
    hd = eng.convert(mp4, "mp4", d / "v1", {"video_height": 1080})[0]
    tiny = eng.convert(mp4, "mp4", d / "v2", {"video_height": 240,
                                              "video_crf": 30})[0]
    hd_h = probe(hd, "stream=height").split("\n")[0]
    tiny_h = probe(tiny, "stream=height").split("\n")[0]
    print(f"  video heights: 1080-option -> {hd_h}, 240-option -> {tiny_h}")
    assert hd_h == "360" and tiny_h == "240", (hd_h, tiny_h)
    assert size(tiny) < size(hd), "CRF option had no effect on size"
    checks.append(("video 1080 vs 240", hd_h, tiny_h, True))

    # ---- audio bitrate
    lo = eng.convert(mp4, "mp3", d / "a1", {"audio_bitrate": "96k"})[0]
    hi = eng.convert(mp4, "mp3", d / "a2", {"audio_bitrate": "320k"})[0]
    print(f"  mp3 96k={size(lo)}B, 320k={size(hi)}B")
    assert size(hi) > size(lo) * 2, "audio bitrate ignored"
    checks.append(("mp3 96k vs 320k", size(lo), size(hi), True))

    # ---- gif height
    g1 = eng.convert(mp4, "gif", d / "g1", {"video_height": 200})[0]
    g2 = eng.convert(mp4, "gif", d / "g2", {"video_height": 400})[0]
    w1, w2 = Image.open(g1).width, Image.open(g2).width
    print(f"  gif heights 200/400 -> widths {w1}/{w2}")
    assert w2 > w1, "gif height ignored"

    # ---- frame spacing
    f1 = eng.convert(mp4, "png-frames", d / "f1", {"frame_every": 1})
    f2 = eng.convert(mp4, "png-frames", d / "f2", {"frame_every": 5})
    import zipfile
    def frame_count(outputs):
        if outputs[0].suffix == '.zip':
            with zipfile.ZipFile(outputs[0]) as archive:
                return len(archive.namelist())
        return len(outputs)
    n1, n2 = frame_count(f1), frame_count(f2)
    print(f"  frames: every 1s -> {n1}, every 5s -> {n2}")
    assert n2 < n1, "frame spacing ignored"
    checks.append(("frames 1s vs 5s", n1, n2, True))

    # ---- text -> pdf page size
    md = S / "notes.md"
    t_a4 = eng.convert(md, "pdf", d / "t1", {"pdf_page": "a4"})[0]
    t_let = eng.convert(md, "pdf", d / "t2", {"pdf_page": "letter"})[0]
    print(f"  text pdf a4={dims(t_a4)} letter={dims(t_let)}")
    assert dims(t_a4) != dims(t_let), "text pdf page size ignored"

    print("\noption effect table:")
    for name, a, b, ok in checks:
        print(f"  {name:28s} {a!s:>12} -> {b!s:>12}  {'ok' if ok else 'FAIL'}")
print("options OK")
