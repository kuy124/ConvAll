"""Native hit testing and persistent chip images."""
import ctypes
import gc
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import convall_ui as ui
app = ui.App()
app.root.update()
app._chrome()
style = ctypes.windll.user32.GetWindowLongW(app.hwnd, -16)
for flag in (0x00C00000, 0x00040000, 0x00010000):
    assert style & flag == flag, 'native caption, resize and maximize required'
assert not app.root.grid_slaves(row=0)[0].bind('<B1-Motion>')
app.root.state('zoomed')
app.root.update()
assert app.root.state() == 'zoomed'
app.root.state('normal')
app.root.update()
chip = ui.Pill(app.root, "test", app.f_body)
chip.configure_pill(selected=True)
name = str(chip._background)
ui._rr_cache.clear()
gc.collect()
assert name in app.root.tk.call('image', 'names')
assert chip.selected and chip._fill() == ui.ACCENT
source = Path(__file__).parent / 'samples' / 'blue.png'
app.list.add([source])
app.root.update()
app.set_target('jpg')
assert app.chips['jpg'].selected
app.set_target('webp')
assert app.chips['webp'].selected and not app.chips['jpg'].selected
app.list.select_all()
assert app.chips['webp'].selected
app.list.select_none()
assert app.chips['webp'].selected
app.root.destroy()
print("native caption, maximize/restore, chip state and image ownership OK")
