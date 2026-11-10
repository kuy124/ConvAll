"""Screenshot states: video options, pdf options, image options."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_ui as ui  # noqa: E402

S = ROOT / "tests" / "samples"
which = sys.argv[1] if len(sys.argv) > 1 else "video"
app = ui.App(paths=[S / "blue.png", S / "clip.mp4", S / "notes.md",
                    S / "tone.mp3"])


def setup():
    row, fmt = {"video": (1, "mkv"), "pdf": (2, "pdf"),
                "image": (0, "jpg"), "audio": (3, "ogg")}[which]
    app.list.sel = {row}
    app.list._notify_select()
    app.list.draw()
    app.set_target(fmt)
    if which == "video":
        app.set_option("video_height", 720)
        app.set_option("video_crf", 28)
        app.status_lbl.configure(text="4 rows ready")
    app.root.update()


app.root.after(800, setup)
app.root.mainloop()