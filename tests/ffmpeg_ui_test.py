"""The ffmpeg strip must: appear when ffmpeg is missing, run the download,
report progress, then hide itself and flip the status dot to ready."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_engine as eng  # noqa: E402

# --- pretend there is no ffmpeg anywhere
eng.ffmpeg = lambda: (_ for _ in ()).throw(eng.ConvertError("missing"))
import convall_ui as ui  # noqa: E402

app = ui.App(paths=[ROOT / "tests" / "samples" / "blue.png"])
app.root.update()

assert app.ff_strip.winfo_ismapped(), "download strip did not appear"
print("strip visible when ffmpeg is missing:", True)
print("engine label:", app.engine_lbl.cget("text"))

# --- stub the downloader: report progress, then a path
fake = ROOT / "tests" / "fake_ffmpeg.exe"
fake.write_bytes(b"stub")


def fake_download(progress=None):
    for i in range(1, 6):
        if progress:
            progress(i * 20 * 1048576, 100 * 1048576)
        time.sleep(0.05)
    return fake


eng.download_ffmpeg = fake_download
app._download_ffmpeg()
deadline = time.time() + 5
while app.ff_busy and time.time() < deadline:
    app.root.update()
    time.sleep(0.05)
app.root.update()
print("after download -> strip visible:", app.ff_strip.winfo_ismapped())
print("status:", app.status_lbl.cget("text"))

assert not app.ff_strip.winfo_ismapped(), "strip should hide after success"
assert "installed" in app.status_lbl.cget("text"), app.status_lbl.cget("text")

# --- and a failure must be reported, not swallowed
eng.ffmpeg = lambda: (_ for _ in ()).throw(eng.ConvertError("missing"))
app.ff_strip.grid()
app.ff_btn.configure_pill(enabled=True)


def boom(progress=None):
    raise eng.ConvertError("couldn't download ffmpeg (HTTP 503)")


eng.download_ffmpeg = boom
app._download_ffmpeg()
deadline = time.time() + 5
while app.ff_busy and time.time() < deadline:
    app.root.update()
    time.sleep(0.05)
app.root.update()
print("on failure -> button:", app.ff_btn.text_, "| msg:",
      app.ff_msg.cget("text"))
assert "Retry" in app.ff_btn.text_, app.ff_btn.text_
assert app.ff_strip.winfo_ismapped(), "strip must stay on failure"

fake.unlink(missing_ok=True)
app.root.destroy()
print("ffmpeg download UI OK")