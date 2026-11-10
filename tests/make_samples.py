import subprocess
from pathlib import Path

from PIL import Image

S = Path(__file__).resolve().parent / "samples"
S.mkdir(parents=True, exist_ok=True)
Image.new("RGBA", (640, 400), (40, 120, 220, 200)).save(S / "blue.png")
Image.new("RGB", (320, 200), (220, 120, 60)).save(S / "warm.jpg")
(S / "rows.csv").write_text("name,n\nx,1\ny,2\n", encoding="utf-8")
(S / "notes.md").write_text("# Todo\n\n" + "Ship the converter. " * 40,
                            encoding="utf-8")
ff = "ffmpeg"
subprocess.run([ff, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                str(S / "tone.mp3")], capture_output=True)
subprocess.run([ff, "-y", "-f", "lavfi", "-i",
                "testsrc2=duration=3:size=640x360:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
                "-shortest", str(S / "clip.mp4")], capture_output=True)
print("samples:", sorted(p.name for p in S.iterdir()))