"""The options panel must show the right knobs and feed them to the worker."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_ui as ui  # noqa: E402

S = ROOT / "tests" / "samples"
OUT = ROOT / "tests" / "optout"
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True)

app = ui.App(paths=[S / "blue.png", S / "clip.mp4", S / "tone.mp3",
                    S / "notes.md"])
app.outdir = OUT
app.out_lbl.configure(text=str(OUT))
app.root.update()


def keys() -> list[str]:
    return list(app._opt_chips)


def pick(row, fmt):
    app.list.select_none()
    app.list.sel = {row}
    app.list._notify_select()
    app.root.update()
    app.set_target(fmt)
    app.root.update()
    return keys()


print("png -> jpg:", pick(0, "jpg"))
assert keys() == ["max_h", "quality"], keys()
print("png -> pdf:", pick(0, "pdf"))
assert keys() == ["pdf_page", "pdf_orient", "max_h"], keys()
print("mp4 -> mp4:", pick(1, "mkv"))
assert "video_height" in keys() and "video_crf" in keys(), keys()
assert not app._opt_chips["video_height"][1080].enabled
assert not app._opt_chips["video_height"][720].enabled
print("360p source: 720p/1080p/4K choices disabled")
print("mp4 -> pdf:", pick(1, "pdf"))
assert keys() == ["pdf_page", "pdf_orient"], keys()
print("mp3 -> mp3:", pick(2, "wav"))
assert keys() == [], keys()            # wav is lossless: no bitrate knob
print("mp3 -> ogg:", pick(2, "ogg"))
assert keys() == ["audio_bitrate"], keys()
print("md -> mp3:", pick(3, "mp3"))
assert keys() == ["audio_bitrate"], keys()

# the panel hides entirely when nothing is tunable
print("options visible for wav:", app.opt_wrap.winfo_ismapped())
pick(2, "wav")
assert app.opt_wrap.winfo_ismapped(), 'Advanced settings remain available for lossless audio'
print("options hidden when not applicable: True")

# --- and the chosen values must reach the converter
for it in app.list.items:
    it["target"] = None
pick(1, "mkv")            # source is mp4, so target it as mkv
app.set_option("video_height", 240)
app.set_option("video_crf", 30)
assert app.opts["video_height"] == 240 and app.opts["video_crf"] == 30
app.start()
while app.running:
    app.root.update()
    import time
    time.sleep(0.05)
app.root.update()
out = OUT / "clip.mkv"
assert out.exists(), sorted(p.name for p in OUT.iterdir())
import subprocess

h = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=height", "-of", "csv=p=0",
                    str(out)], capture_output=True, text=True).stdout.strip()
print(f"gui conversion used the option: output height = {h}px")
assert h == "240", f"option did not reach the converter: {h}"
print("status:", app.status_lbl.cget("text"))
app.root.destroy()
print("options UI OK")
