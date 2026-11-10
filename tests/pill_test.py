"""Pill labels stay centered in every state and after resizing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import tkinter as tk
import tkinter.font as font
from convall_ui import Pill

root = tk.Tk()
pill = Pill(root, 'Convert → PDF', font.Font(size=12))
pill.pack(fill='both', expand=True)
root.geometry('300x80')
root.update()
for text in ('png', 'PDF', 'Convert 12 files', '720p'):
    for selected in (False, True):
        pill.configure_pill(text=text, selected=selected)
        root.update()
        label = next(i for i in pill.find_all() if pill.type(i) == 'text')
        l, t, r, b = pill.bbox(label)
        assert abs((l+r)/2 - pill.winfo_width()/2) <= .5
        assert abs((t+b)/2 - pill.winfo_height()/2) <= .5
root.destroy()
print('pill centering OK: different labels, states, and stretched bounds')
