"""Chip grid must scroll (with a thumb) when the window gets short."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_ui as ui  # noqa: E402

S = ROOT / "tests" / "samples"
app = ui.App(paths=[S / "clip.mp4"])
app.root.update()
app.set_target("png")

sb = app.chip_scroll
app.root.geometry(f"{ui.P(1010)}x{ui.P(520)}")   # short window
app.root.update()
app.root.after(300, lambda: None)
import time

time.sleep(0.5)
app.root.update()

need = sb.inner.winfo_reqheight()
view = sb.winfo_height()
thumb = bool(sb.find_withtag("thumb"))
print(f"content {need}px in a {view}px viewport | scroll thumb: {thumb}")
assert need > view, "expected overflow at this window size"
assert thumb, "thumb should be drawn when the grid overflows"

sb._wheel(type("E", (), {"delta": -120})())
app.root.update()
print("scrolled to", tuple(round(v, 2) for v in sb.yview()))
assert sb.yview()[0] > 0, "wheel did not scroll"

# and the save-to row must still be on screen
app.root.update_idletasks()
y = app.out_lbl.winfo_rooty() - app.root.winfo_rooty()
print(f"save-to row at y={y} of {app.root.winfo_height()} -> visible:",
      y < app.root.winfo_height() - 10)
assert y < app.root.winfo_height() - 10, "SAVE TO pushed off screen"
app.root.destroy()
print("chip scrolling OK")
