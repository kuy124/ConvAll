"""Check the shipped window's native Snap prerequisites and keyboard docking."""
import ctypes
import subprocess
import time
from pathlib import Path
from ctypes import wintypes

root = Path(__file__).resolve().parent.parent
u = ctypes.windll.user32
u.SetProcessDPIAware()
proc = subprocess.Popen([str(root / 'dist' / 'ConvAll.exe')])
hwnd = 0
try:
    for _ in range(100):
        hwnd = u.FindWindowW(None, 'ConvAll')
        if hwnd:
            break
        time.sleep(.25)
    assert hwnd, 'window did not open'
    time.sleep(2)
    style = u.GetWindowLongW(hwnd, -16)
    assert style & 0x00C00000 == 0x00C00000
    assert style & 0x00050000 == 0x00050000
    # Focus can be denied by Windows; don't send shortcuts to another app.
    u.ShowWindow(hwnd, 9)
    u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)
    u.keybd_event(0x12, 0, 0, 0)
    u.SetForegroundWindow(hwnd)
    u.keybd_event(0x12, 0, 2, 0)
    time.sleep(.5)
    assert u.GetForegroundWindow() == hwnd, 'could not focus Snap test window'
    u.keybd_event(0x5B, 0, 0, 0)
    u.keybd_event(0x25, 0, 0, 0)
    u.keybd_event(0x25, 0, 2, 0)
    u.keybd_event(0x5B, 0, 2, 0)
    time.sleep(1)
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    screen = u.GetSystemMetrics(0)
    assert abs((r.right-r.left) - screen/2) < 60, (r.left, r.right, screen)
    print('shipped exe: Windows Snap left OK')
finally:
    if hwnd:
        u.PostMessageW(hwnd, 0x10, 0, 0)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()
