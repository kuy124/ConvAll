"""The in-app ffmpeg download must actually fetch a working binary."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_engine as eng  # noqa: E402

tmp = Path(tempfile.mkdtemp())
eng.ffmpeg_dir = lambda: tmp                 # don't touch the real app folder
eng.FFMPEG_URLS = eng.FFMPEG_URLS[:1]        # primary mirror only

sizes = []


def prog(got, total):
    sizes.append((got, total))


exe = eng.download_ffmpeg(prog)
print(f"downloaded: {exe.name} {exe.stat().st_size / 1048576:.1f} MB "
      f"in {len(sizes)} chunks")
assert exe.exists() and exe.stat().st_size > 30 * 1048576, "ffmpeg too small"
probe = tmp / "ffprobe.exe"
assert probe.exists(), "ffprobe not extracted alongside ffmpeg"

# it must actually run
out = subprocess.run([str(exe), "-version"], capture_output=True, text=True)
first = out.stdout.splitlines()[0]
print("runs:", first[:60])
assert "ffmpeg version" in first

# and the engine must find it when it's the only copy around
eng.ffmpeg = (lambda orig: (lambda: str(exe)))(eng.ffmpeg)
wav = tmp / "beep.wav"
subprocess.run([str(exe), "-y", "-f", "lavfi", "-i",
                "sine=frequency=660:duration=1", str(wav)], capture_output=True)
src = tmp / "in.wav"
shutil.copy(wav, src)
outs = eng.convert(src, "mp3", tmp)
print("converted with downloaded ffmpeg:", Path(outs[0]).name,
      Path(outs[0]).stat().st_size, "bytes")
assert Path(outs[0]).stat().st_size > 1000
shutil.rmtree(tmp, ignore_errors=True)
print("ffmpeg downloader OK")