"""Capture real UI documentation images without user files or preferences."""
import ctypes
import os
import runpy
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from PIL import Image
import convall_settings


def capture(window, output):
    # shot.py uses PrintWindow; retarget FindWindow by giving each dialog the
    # standard title for the duration of its capture.
    old = window.title()
    original = ctypes.windll.user32.FindWindowW
    ctypes.windll.user32.FindWindowW = lambda _class, _name: window.winfo_id() if window.overrideredirect() else ctypes.windll.user32.GetParent(window.winfo_id())
    argv = sys.argv
    try:
        sys.argv = ['shot.py', str(output)]
        runpy.run_path(str(ROOT / 'tests/shot.py'), run_name='__main__')
    finally:
        sys.argv = argv
        ctypes.windll.user32.FindWindowW = original
        window.title(old)


def settle(app):
    end = time.monotonic() + .6
    while time.monotonic() < end:
        app.root.update()
        time.sleep(.02)


with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    convall_settings.settings_path = lambda: d/'settings.json'
    import convall_ui as ui
    Image.new('RGB', (1280, 720), '#287c9e').save(d/'Holiday photo.png')
    (d/'Meeting notes.md').write_text('# Meeting notes\n\nOur next project starts Monday.', encoding='utf-8')
    (d/'Monthly report.csv').write_text('Month,Sales\nJanuary,120\nFebruary,180\n', encoding='utf-8')
    app = ui.App(paths=[d/'Holiday photo.png', d/'Meeting notes.md', d/'Monthly report.csv'])
    settle(app)
    for index, target in enumerate(('jpg', 'pdf', 'xlsx')):
        app.list.sel = {index}
        app.set_target(target)
    app.list.sel = {0}
    app._refresh_targets()
    app.list.draw()
    app.status_lbl.configure(text='Choose a format for each file, then convert.')
    out = ROOT/'screenshots'
    out.mkdir(exist_ok=True)
    settle(app)
    capture(app.root, out/'main.png')
    app.list.sel = {1}
    app._refresh_targets()
    app.advanced_options()
    settle(app)
    capture(app._advanced_dialog, out/'advanced.png')
    app._advanced_dialog.event_generate('<Escape>')
    settle(app)
    app.change_theme('Nord')
    settle(app)
    capture(app.root, out/'nord.png')
    app.root.destroy()
Image.open(ROOT/'assets/icon.ico').save(ROOT/'assets/icon.png')
