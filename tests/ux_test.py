"""Centered singleton dialog and deterministic theme toggle."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
import convall_ui as ui

app = ui.App(paths=[ROOT/'tests/samples/clip.mp4'])
app.root.update()
app.set_target('mkv')
app.list.sel = {0}
app.root.update()
app.advanced_options()
app.root.update()
dialog = app._advanced_dialog
dx = dialog.winfo_rootx() + dialog.winfo_width()/2
dy = dialog.winfo_rooty() + dialog.winfo_height()/2
cx = app.root.winfo_rootx() + app.root.winfo_width()/2
cy = app.root.winfo_rooty() + app.root.winfo_height()/2
assert abs(dx-cx) < 20 and abs(dy-cy) < 40, (dx-cx, dy-cy)
app.advanced_options()
assert app._advanced_dialog is dialog
dialog.event_generate('<Escape>')
app.root.update()
assert app._advanced_dialog is None
for _ in range(4):
    app.theme_button._on_release(None)
    app.root.update()
    assert app._theme_popup is not None
    app.theme_button._on_release(None)
    app.root.update()
    assert app._theme_popup is None
app.toggle_theme_menu()
app.list.event_generate('<Button-1>', x=200, y=200)
app.root.update()
assert app._theme_popup is None
app.root.destroy()
print('dialog centered, singleton, Escape cancel; theme toggle and outside dismissal OK')
