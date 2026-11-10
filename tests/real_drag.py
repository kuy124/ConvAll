"""Real-input proof: minimize the terminal, drag the exe with the actual mouse
cursor, then put the terminal back. No synthetic messages anywhere."""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "tests" / "samples"
u = ctypes.windll.user32
u.SetProcessDPIAware()
SW_MINIMIZE, SW_RESTORE, SW_SHOW = 6, 9, 5
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def rect(h):
    r = RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def class_of(h):
    buf = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(h, buf, 64)
    return buf.value


def find_terminals():
    found = []
    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def _cb(h, _lp):
        if u.IsWindowVisible(h) and "wezterm" in class_of(h):
            found.append(h)
        return True

    u.EnumWindows(cb(_cb), 0)
    return found


def click(x, y):
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.3)


term = find_terminals()
obscuring = []
enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def collect_obscuring(h, _):
    if u.IsWindowVisible(h) and class_of(h) == 'Chrome_WidgetWin_1':
        obscuring.append(h)
    return True
u.EnumWindows(enum_proc(collect_obscuring), 0)
term += obscuring
print("terminal windows:", len(term))
proc = subprocess.Popen([str(ROOT / "dist" / "ConvAll.exe"),
                         str(S / "clip.mp4")])
try:
    deadline = time.time() + 40
    hwnd = 0
    while time.time() < deadline and not hwnd:
        hwnd = u.FindWindowW(None, "ConvAll")
        time.sleep(0.4)
    assert hwnd, "app did not open"
    time.sleep(3)

    for h in term:                       # get the terminal out of the way
        u.ShowWindow(h, SW_MINIMIZE)
    time.sleep(1.0)

    # Do not move Tk's outer HWND behind Tk's back before the drag.
    u.ShowWindow(hwnd, SW_RESTORE)
    u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    print("foreground is the app:", u.GetForegroundWindow() == hwnd)

    # sanity: a real click on a queue row must select it (input truly arrives)
    x0, y0, x1, y1 = rect(hwnd)
    print("window rect:", x0, y0, x1, y1)
    u.SetCursorPos(x0 + 300, y0 + 140)
    time.sleep(0.2)
    under = u.WindowFromPoint(wintypes.POINT(x0 + 300, y0 + 140))
    print("under cursor:", class_of(under))

    # real drag on the title bar
    gx, gy = x0 + 520, y0 + 30
    u.SetCursorPos(gx, gy)
    time.sleep(0.2)
    u.mouse_event(0x0002, 0, 0, 0, 0)          # press
    time.sleep(0.2)
    for i in range(1, 16):
        u.SetCursorPos(gx - i * 9, gy + i * 6)
        time.sleep(0.03)
    u.mouse_event(0x0004, 0, 0, 0, 0)          # release
    time.sleep(0.5)

    nx0, ny0 = rect(hwnd)[:2]
    print(f"real drag moved the window by ({nx0 - x0}, {ny0 - y0})"
          f" — wanted (-135, 90)")
    assert (nx0 - x0, ny0 - y0) == (-135, 90), "real drag did not move it 1:1"

    # and a press-release without motion must not move it
    u.SetCursorPos(nx0 + 400, ny0 + 30)
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.3)
    fx0, fy0 = rect(hwnd)[:2]
    assert (fx0, fy0) == (nx0, ny0), "a click moved the window"
    print("real click does not move the window")
    print("REAL DRAG OK")
finally:
    try:
        u.PostMessageW(hwnd, 0x0010, 0, 0)
    except Exception:
        pass
    time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
    for h in term:                       # always give the terminal back
        u.ShowWindow(h, SW_RESTORE)
        u.SetForegroundWindow(h)
    print("terminal restored")
