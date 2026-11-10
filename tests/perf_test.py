"""In-process check: drag goes native, resize stays fast, selection works."""
import ctypes
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import convall_ui as ui  # noqa: E402

S = ROOT / "tests" / "samples"
app = ui.App(paths=[S / "blue.png", S / "clip.mp4", S / "tone.mp3"])
app.root.update()
# Exclude startup chrome/theme/layout timers from the resize measurement.
deadline = time.monotonic() + 0.6
while time.monotonic() < deadline:
    app.root.update()
    time.sleep(0.01)

# Native dragging is exercised with real mouse input by real_drag.py.
print("drag: deferred native move; real mouse check runs against the exe")

# ---- 2. resize cost: measure the worst repaint while growing the window
u = ctypes.windll.user32
u.SetProcessDPIAware()
hwnd = app.hwnd
step = []
for i in range(1, 11):
    w, h = ui.P(1010) + 16 * i, ui.P(660) + 10 * i
    t = time.perf_counter()
    u.SetWindowPos(hwnd, 0, 0, 0, w, h, 0x0006)   # NOMOVE | NOZORDER
    u.UpdateWindow(hwnd)
    app.root.update()
    step.append((time.perf_counter() - t) * 1000)
avg, worst = sum(step) / len(step), max(step)
print(f"resize: {len(step)} steps, avg {avg:.1f} ms, worst {worst:.1f} ms")
assert worst < 250, f"resize too slow: {worst:.0f} ms"

# ---- 3. after the drag settles, corners come back (rounded, not flat)
app.root.after(220, lambda: None)
time.sleep(0.3)
app.root.update()
assert not ui.RESIZE["active"], "still in cheap-resize mode"
print("resize: rounded chrome restored after settling")

# ---- 4. per-row targets survive selection + chip clicks
app.list.items[0]["target"] = "jpg"
app.list.items[1]["target"] = "mp3"
app.list.items[2]["target"] = "pdf"
app.list.sel = {0, 1}
app.list._notify_select()
assert "Convert 3" in app.btn_go.text_, app.btn_go.text_
app.list.sel = {0, 1}
app.list._notify_select()
print(f"cta (all set): {app.btn_go.text_!r}")
app.set_target("gif")
assert app.list.items[0]["target"] == "gif", "chip did not apply to selection"
assert app.list.items[2]["target"] == "pdf", "chip touched an unselected row"
print("selection: chips apply to selected rows only")
app.root.destroy()
print("OK")
