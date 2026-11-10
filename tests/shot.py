import ctypes, sys
from ctypes import wintypes

from PIL import Image

u = ctypes.windll.user32
g = ctypes.windll.gdi32
u.SetProcessDPIAware()
hwnd = u.FindWindowW(None, "ConvAll")
if not hwnd:
    print("no window")
    sys.exit(1)
r = wintypes.RECT()
u.GetWindowRect(hwnd, ctypes.byref(r))
w, h = r.right - r.left, r.bottom - r.top

hdc_win = u.GetWindowDC(hwnd)
hdc = g.CreateCompatibleDC(hdc_win)
bmp = g.CreateCompatibleBitmap(hdc_win, w, h)
g.SelectObject(hdc, bmp)
ok = u.PrintWindow(hwnd, hdc, 2)


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


bi = BIH()
bi.biSize = ctypes.sizeof(BIH)
bi.biWidth, bi.biHeight = w, -h
bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
buf = ctypes.create_string_buffer(w * h * 4)
g.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(sys.argv[1])
g.DeleteObject(bmp)
g.DeleteDC(hdc)
u.ReleaseDC(hwnd, hdc_win)
print(f"ok={ok} {w}x{h}")