"""ConvAll UI - hand-drawn dark window, no native widgets, no title bar.

Everything visible is drawn by us: rounded panels, pills, chips, the file
queue and the progress bar. Only the window frame comes from Windows, with
its caption stripped so the app owns the whole surface.
"""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

from convall_engine import (GROUP_ORDER, OPTIONS, ConvertError, convert,
                            ext_of, kind_of, label_of, option_value,
                            options_for, source_height, targets_for, targets_grouped)

# ------------------------------------------------------------------ theme ---

BG = "#080b10"
PANEL = "#141a23"
PANEL_HI = "#1d242f"
LINE = "#232a36"
TEXT = "#e8eef7"
MUTED = "#8b97a8"
DIM = "#8492a6"
ACCENT = "#3f7cff"
ACCENT_HI = "#5b90ff"
ACCENT_SOFT = "#1b2b4d"
OK = "#35c07f"
ERR = "#ff6b6b"
WARN = "#f0b429"

KIND_COLOR = {"image": "#49a0ff", "audio": "#b07cff", "video": "#2fd3b0",
              "pdf": "#ff9166", "table": "#ffc857", "text": "#8fa3bf",
              "?": DIM}

GROUP_LABEL = {"images": "IMAGES", "audio": "AUDIO", "video": "VIDEO",
               "docs": "DOCUMENTS & DATA"}


def _dpi_scale() -> float:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, dc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


S = _dpi_scale()


def P(n: float) -> int:
    return int(round(n * S))


# While the user drags an edge, Windows fires Configure continuously. Drawing
# antialiased corners at 3x supersample on every tick is what made resize crawl,
# so during a resize we paint flat rectangles and only round once it settles.
RESIZE = {"active": False, "job": None}
SETTLERS: list = []          # widgets that repaint themselves after a resize
PANELS: list = []


def settle_resize():
    """Resize stopped: put the antialiased corners back."""
    RESIZE["active"] = False
    for fn in list(SETTLERS):
        try:
            fn()
        except Exception:
            pass


def note_resize(widget):
    RESIZE["active"] = True
    if RESIZE["job"]:
        try:
            widget.after_cancel(RESIZE["job"])
        except Exception:
            pass
    RESIZE["job"] = widget.after(150, settle_resize)


def res(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "assets"))
    return base / name


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


class SizeWatch:
    """Callback only when a widget's *size* changes, not its position.

    Tk sends <Configure> for moves too; repainting the queue on every motion
    event is what made dragging look like a CS 1.6 spectator glitch.
    """

    def __init__(self, widget, callback):
        self.widget, self.callback = widget, callback
        self.size = (0, 0)
        widget.bind("<Configure>", self._on_conf, add="+")

    def _on_conf(self, e):
        size = (e.width, e.height)
        if size == self.size:
            return
        self.size = size
        self.callback(e)


# ------------------------------------------------------- rounded drawing ----

_rr_cache: dict[tuple, ImageTk.PhotoImage] = {}


def rr(w: int, h: int, radius: int, fill: str, bg: str,
       border: str | None = None, bw: int = 1) -> ImageTk.PhotoImage:
    """Antialiased rounded rectangle as an opaque image (crisp on any DPI)."""
    w, h = max(1, int(w)), max(1, int(h))
    key = (w, h, radius, fill, bg, border, bw)
    hit = _rr_cache.get(key)
    if hit is not None:
        return hit
    k = 2 if max(w, h) > 260 else 3  # supersample: big panels need less
    img = Image.new("RGB", (w * k, h * k), bg)
    d = ImageDraw.Draw(img)
    r = max(0, min(radius * k, h * k // 2))
    d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=r, fill=fill,
                        outline=border if border else None,
                        width=bw * k if border else 1)
    img = img.resize((w, h), Image.LANCZOS)
    ph = ImageTk.PhotoImage(img)
    if len(_rr_cache) > 700:
        _rr_cache.clear()
    _rr_cache[key] = ph
    return ph


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def ellipsis(text: str, font: tkfont.Font, maxpx: float) -> str:
    if font.measure(text) <= maxpx:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= maxpx:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + "…") if lo else "…"


def shade(hexcolor: str, amount: float) -> str:
    """Darken (negative) or lighten a #rrggbb colour."""
    hexcolor = hexcolor.lstrip("#")
    if len(hexcolor) != 6:
        return "#" + hexcolor
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
    if amount < 0:
        r, g, b = (int(c * (1 + amount)) for c in (r, g, b))
    else:
        r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


# ----------------------------------------------------------------- widgets ---

class ImageCanvas(tk.Canvas):
    """Own every displayed PhotoImage even after the shared cache evicts it."""

    def create_image(self, *args, **kwargs):
        item = super().create_image(*args, **kwargs)
        if not hasattr(self, "_images"):
            self._images = {}
        self._images[item] = kwargs.get("image")
        return item

    def delete(self, *tags):
        images = getattr(self, "_images", {})
        for tag in tags:
            for item in self.find_withtag(tag):
                images.pop(item, None)
        return super().delete(*tags)


class Pill(ImageCanvas):
    """Fixed-size rounded button/chip drawn with antialiased corners."""

    def __init__(self, master, text, font, *, bg=PANEL, fill=PANEL_HI,
                 fg=TEXT, hover=None, border=None, radius=9, padx=14, pady=8,
                 command=None, min_width=0, cursor="hand2", sel_fill=None):
        self.text_ = text
        self.font_ = font
        self.fill_, self.hover_ = fill, hover or fill
        self.fg_, self.border_ = fg, border
        self.radius_, self.padx, self.pady = P(radius), P(padx), P(pady)
        w = max(P(min_width), font.measure(text) + 2 * self.padx)
        h = font.metrics("linespace") + 2 * self.pady
        super().__init__(master, width=w, height=h, bg=bg, bd=0,
                         highlightthickness=0, cursor=cursor)
        self.w_, self.h_ = w, h
        self.command = command
        self.sel_fill = sel_fill or ACCENT
        self.selected = False
        self.enabled = True
        self._hovering = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._resize)
        self._draw()

    def _resize(self, event):
        self.w_, self.h_ = event.width, event.height
        self._draw()

    # state -------------------------------------------------------------
    def _fill(self):
        if not self.enabled:
            return "#182231" if self.fill_ in (ACCENT, ACCENT_HI) else PANEL_HI
        if self.selected:
            return self.sel_fill
        if getattr(self, "_down", False):
            return shade(self.hover_ if self._hovering else self.fill_, -0.12)
        return self.hover_ if self._hovering else self.fill_

    def _fg(self):
        if not self.enabled:
            return DIM
        return "#ffffff" if self.selected else self.fg_

    def _draw(self):
        self.delete("all")
        self._background = rr(self.w_, self.h_, self.radius_, self._fill(),
                              self.cget("bg"), self.border_,
                              P(1) if self.border_ else 1)
        self.create_image(0, 0, anchor="nw",
                          image=self._background)
        label = self.create_text(self.w_ / 2, self.h_ / 2, text=self.text_,
                                 anchor="center", justify="center",
                                 fill=self._fg(), font=self.font_)
        bounds = self.bbox(label)
        if bounds:
            left, top, right, bottom = bounds
            self.move(label, (self.w_ - left - right) / 2,
                      (self.h_ - top - bottom) / 2)

    def configure_pill(self, *, selected=None, enabled=None, text=None,
                       fill=None, hover=None):
        if selected is not None:
            self.selected = selected
        if enabled is not None:
            self.enabled = enabled
        if text is not None:
            self.text_ = text
        if fill is not None:
            self.fill_ = fill
        if hover is not None or fill is not None:
            self.hover_ = hover or self.fill_
        self._draw()

    # events ------------------------------------------------------------
    def _on_enter(self, _e):
        self._hovering = True
        self._draw()

    def _on_leave(self, _e):
        self._hovering = False
        self._draw()

    def _on_press(self, _e):
        if self.enabled:
            self._down = True
            self._draw()

    def _on_release(self, _e):
        self._down = False
        self._draw()
        if self.enabled and self.command:
            self.command()


class Panel(ImageCanvas):
    """Rounded card hosting a normal frame inside."""

    def __init__(self, master, *, bg=BG, fill=PANEL, radius=13, pad=1,
                 border=None):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fill, self.radius, self.pad, self.border = fill, P(radius), P(pad), border
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(self.pad, self.pad, anchor="nw",
                                       window=self.inner)
        self._size = (0, 0)
        self.bind("<Configure>", self._on_conf)
        PANELS.append(self)
        SETTLERS.append(self.redraw_bg)

    def redraw_bg(self):
        w, h = self._size
        if w < 2 or h < 2:
            return
        self.itemconfigure(self._win, width=max(1, w - 2 * self.pad),
                           height=max(1, h - 2 * self.pad))
        self.delete("bg")
        self.create_image(0, 0, anchor="nw",
                          image=rr(w, h, self.radius, self.fill,
                                   self.cget("bg"), self.border,
                                   P(1) if self.border else 1),
                          tags="bg")
        self.tag_lower("bg")

    def _on_conf(self, e):
        w, h = max(1, e.width), max(1, e.height)
        if (w, h) == self._size:
            return
        self._size = (w, h)
        self.delete("bg")
        if RESIZE["active"]:
            # Mid-drag: leave content where it is and let the canvas paint a
            # flat fill. Re-laying out the panel on every motion event is what
            # made resizing crawl. settle_resize() puts it all back.
            self.create_rectangle(0, 0, w, h, fill=self.fill, outline="",
                                  tags="bg")
            self.tag_lower("bg")
            return
        self.redraw_bg()


class ScrollBox(ImageCanvas):
    """A scrollable viewport holding a frame of placed widgets (chip grid)."""

    def __init__(self, master, *, bg=PANEL, on_size=None):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.inner = tk.Frame(self, bg=bg)
        self._win = self.create_window(0, 0, anchor="nw", window=self.inner)
        self._vw, self._vh = 0, 0
        self.on_size = on_size
        self.bind("<Configure>", self._on_conf)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Enter>", lambda _e: self.focus_set())
        self.inner.bind("<Configure>", lambda _e: self._sync_height())

    def _on_conf(self, e):
        if (e.width, e.height) == (self._vw, self._vh):
            return
        self._vw, self._vh = e.width, e.height
        self.itemconfigure(self._win, width=max(1, e.width - P(9)))
        self._sync_height()
        if self.on_size:
            self.on_size(e.width)

    def _sync_height(self):
        need = self.inner.winfo_reqheight()
        tall = max(need, self._vh)
        self.itemconfigure(self._win, height=tall)
        self.configure(scrollregion=(0, 0, self._vw, tall))
        self._draw_thumb(need)

    def _draw_thumb(self, need):
        """Thumb in the right gutter, so an overflowing grid is obvious."""
        self.delete("thumb")
        if need <= self._vh + 2 or self._vw < P(20):
            return
        top, bottom = self.yview()
        span = max(0.001, bottom - top)
        h = max(P(26), int(self._vh * span))
        y = P(2) + int((self._vh - P(4) - h) * (top / max(0.001, 1 - span)))
        self.create_image(self._vw - P(6), y, anchor="nw",
                          image=rr(P(4), h, P(2), "#39465a", PANEL),
                          tags="thumb")

    def _wheel(self, e):
        self.yview_scroll(int(-e.delta / 120) * 2, "units")
        self._draw_thumb(self.inner.winfo_reqheight())
        return "break"

    def reset_scroll(self):
        self.yview_moveto(0)


class Progress(ImageCanvas):
    def __init__(self, master, bg=PANEL, height=6, fill=ACCENT, track="#191e27"):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0,
                         height=P(height))
        self.value_, self.max_ = 0, 1
        self.fill, self.track, self.h = fill, track, P(height)
        SizeWatch(self, lambda _e: self._draw())
        SETTLERS.append(self._draw)

    def set(self, value, maximum):
        self.value_, self.max_ = value, max(1, maximum)
        self._draw()

    def _draw(self):
        if RESIZE["active"] and self.value_ > 0:
            return          # mid-drag: keep the last paint
        self.delete("all")
        w = self.winfo_width()
        h = self.h
        if w < 4:
            return
        if self.value_ <= 0:  # idle: no track, no bar
            return
        self.create_image(0, 0, anchor="nw",
                          image=rr(w, h, h // 2, self.track, self.cget("bg")))
        frac = 0 if not self.max_ else min(1.0, self.value_ / self.max_)
        if frac > 0:
            fw = max(h, int(w * frac))
            self.create_image(0, 0, anchor="nw",
                              image=rr(fw, h, h // 2, self.fill, self.cget("bg")))


class FileList(ImageCanvas):
    """The queue as a table: select rows, each row carries its own target."""
    ROW = 34
    GAP = 4
    BADGE_W = 38
    PILL_W = 80

    def __init__(self, master, *, bg=PANEL, on_change=None, on_open=None,
                 on_hover=None, on_select=None):
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.items: list[dict] = []
        self.sel: set[int] = set()
        self.anchor = -1
        self.hover = -1
        self.hover_badge = False
        self.scroll = 0
        self.font = tkfont.Font(family="Segoe UI", size=-P(12))
        self.small = tkfont.Font(family="Segoe UI", size=-P(10))
        self.badge = tkfont.Font(family="Segoe UI", size=-P(9), weight="bold")
        self.pill_font = tkfont.Font(family="Segoe UI", size=-P(10))
        self.on_change = on_change
        self.on_open = on_open
        self.on_hover = on_hover
        self.on_select = on_select
        SizeWatch(self, lambda _e: self.draw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self.bind("<Double-Button-1>", self._dblclick)
        self.bind("<MouseWheel>", self._wheel)
        SETTLERS.append(self.draw)

    # data --------------------------------------------------------------
    def paths(self) -> list[Path]:
        return [i["path"] for i in self.items]

    def selected(self) -> list[int]:
        return sorted(self.sel)

    def active_paths(self) -> list[Path]:
        """Rows a format chip applies to: the selection, else everything."""
        idx = self.selected() or list(range(len(self.items)))
        return [self.items[i]["path"] for i in idx]

    def add(self, paths) -> int:
        have = {str(i["path"]) for i in self.items}
        added = 0
        for p in paths:
            p = Path(str(p).strip().strip("{}").strip('"'))
            if p.is_file() and str(p) not in have:
                self.items.append({"path": p, "state": "queued", "note": "",
                                   "target": None, "size": p.stat().st_size})
                have.add(str(p))
                added += 1
        if added:
            self._changed()
        return added

    def clear(self):
        self.items.clear()
        self.sel.clear()
        self.anchor = -1
        self.scroll = 0
        self._changed()

    def remove(self, idx):
        if not 0 <= idx < len(self.items):
            return
        del self.items[idx]
        self.sel = {j - 1 if j > idx else j for j in self.sel if j != idx}
        self.anchor = -1
        self._changed()

    def select_all(self):
        self.sel = set(range(len(self.items)))
        self._notify_select()
        self.draw()

    def select_none(self):
        self.sel.clear()
        self.anchor = -1
        self._notify_select()
        self.draw()

    def set_state(self, idx, state, note=""):
        if 0 <= idx < len(self.items):
            self.items[idx]["state"] = state
            self.items[idx]["note"] = note
            self.draw()

    def assign(self, target, indices=None) -> tuple[int, int]:
        """Give a target to the rows that can actually make it.

        Returns (assigned, skipped) so the caller can say what happened.
        """
        idx = indices if indices is not None else (
            self.selected() or list(range(len(self.items))))
        done = skipped = 0
        for i in idx:
            if not 0 <= i < len(self.items):
                continue
            if target not in targets_for(self.items[i]["path"]):
                skipped += 1
                continue
            self.items[i]["target"] = target
            if self.items[i]["state"] in ("ok", "failed", "cancelled"):
                self.items[i]["state"] = "queued"
                self.items[i]["note"] = ""
            done += 1
        self.draw()
        self._notify_select()
        return done, skipped

    def _changed(self):
        self.draw()
        if self.on_change:
            self.on_change()

    def _notify_select(self):
        if self.on_select:
            self.on_select()

    # geometry ----------------------------------------------------------
    def _rowbox(self, i):
        y = P(self.GAP) + i * P(self.ROW + self.GAP) - self.scroll
        return y, P(self.ROW)

    def _hit(self, y):
        y += self.scroll - P(self.GAP)
        i = int(y // P(self.ROW + self.GAP))
        return i if 0 <= i < len(self.items) else -1

    def _content_h(self):
        return len(self.items) * P(self.ROW + self.GAP) + P(self.GAP)

    # events ------------------------------------------------------------
    def _motion(self, e):
        i = self._hit(e.y)
        badge = i >= 0 and e.x < P(12) + P(self.BADGE_W) + P(8)
        if (i, badge) != (self.hover, self.hover_badge):
            self.hover, self.hover_badge = i, badge
            self.configure(cursor="hand2" if i >= 0 else "")
            if self.on_hover and i != self.hover:
                self.on_hover(i if i >= 0 else None)
            self.draw()
        if self.on_hover and i != getattr(self, "_last_hover", -1):
            self._last_hover = i
            if i >= 0:
                self.on_hover(i)

    def _leave(self, _e):
        self.hover, self.hover_badge = -1, False
        self._last_hover = -1
        if self.on_hover:
            self.on_hover(None)
        self.draw()

    def _click(self, e):
        i = self._hit(e.y)
        if i < 0:
            self.sel.clear()
            self._notify_select()
            self.draw()
            return
        if self.hover_badge:              # badge doubles as delete on hover
            self.remove(i)
            return
        ctrl = bool(e.state & 0x0004)
        shift = bool(e.state & 0x0001)
        if shift and self.anchor >= 0:
            lo, hi = sorted((self.anchor, i))
            self.sel = set(range(lo, hi + 1))
        elif ctrl:
            self.sel ^= {i}
            self.anchor = i
        else:
            self.sel = {i}
            self.anchor = i
        self._notify_select()
        self.draw()

    def _dblclick(self, e):
        i = self._hit(e.y)
        if not self.items and getattr(self, 'on_pick', None):
            self.on_pick()
            return
        if i >= 0 and self.on_open:
            self.on_open(i)

    def _wheel(self, e):
        maxs = max(0, self._content_h() - self.winfo_height())
        self.scroll = max(0, min(maxs, self.scroll - int(e.delta / 2)))
        self.draw()

    # painting ----------------------------------------------------------
    def draw(self):
        if RESIZE["active"]:
            return          # mid-drag: keep the last paint, re-fit on settle
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        if not self.items:
            self._draw_empty(w, h)
            return
        for i, it in enumerate(self.items):
            y, rh = self._rowbox(i)
            if y > h or y + rh < 0:
                continue
            self._draw_row(i, it, y, rh, w)
        total = self._content_h()
        if total > h:
            bh = max(P(28), int(h * h / total))
            by = int((h - bh) * self.scroll / max(1, total - h))
            self.create_image(w - P(4), by, anchor="nw",
                              image=rr(P(3), bh, P(2), LINE, PANEL))

    def _draw_empty(self, w, h):
        pad = P(14)
        self.create_rectangle(pad, pad, w - pad, h - pad, outline=LINE,
                              dash=(P(4), P(4)))
        cy = h / 2
        self.create_text(w / 2, cy - P(14), text="Drop files here",
                         fill=MUTED, font=tkfont.Font(family="Segoe UI",
                                                      size=-P(14)))
        self.create_text(w / 2, cy + P(12),
                         text="then pick a format for each one, per row",
                         fill=DIM, font=self.small)

    def _draw_row(self, i, it, y, rh, w):
        kind = kind_of(it["path"])
        state, tgt = it["state"], it.get("target")
        if i in self.sel:
            bg = ACCENT_SOFT
        elif i == self.hover:
            bg = PANEL_HI
        else:
            bg = None
        if bg:
            if RESIZE["active"]:
                self.create_rectangle(P(2), y, w - P(4), y + rh, fill=bg,
                                      outline="")
            else:
                self.create_image(P(2), y, anchor="nw",
                                  image=rr(w - P(6), rh, P(8), bg, PANEL))

        # kind badge (turns into a delete button when hovered)
        bx, bw_, bh = P(12), P(self.BADGE_W), P(22)
        kill = self.hover_badge and i == self.hover
        col = ERR if kill else KIND_COLOR.get(kind, DIM)
        self.create_image(bx, y + (rh - bh) / 2, anchor="nw",
                          image=rr(bw_, bh, P(5), col, bg or PANEL))
        label = "✕" if kill else (ext_of(it["path"])[:4].upper() or "?")
        self.create_text(bx + bw_ / 2, y + rh / 2, text=label,
                         fill="#0b0e13", font=self.badge)

        # target pill on the right
        pw, ph = P(self.PILL_W), P(20)
        px = w - P(10) - pw
        py = y + (rh - ph) / 2
        if tgt:
            self.create_image(px, py, anchor="nw",
                              image=rr(pw, ph, P(6), "#2b3d61", bg or PANEL))
            self.create_text(px + pw / 2, y + rh / 2,
                             text=ellipsis(label_of(tgt), self.pill_font,
                                           pw - P(8)),
                             fill="#cfe0ff", font=self.pill_font)
        else:
            self.create_text(px + pw / 2, y + rh / 2, text="no format",
                             fill="#4c5666", font=self.pill_font)

        # name + status
        name_x = bx + bw_ + P(10)
        right = px - P(8)
        state_col = {"queued": DIM, "converting": ACCENT, "ok": OK,
                     "failed": ERR, "cancelled": WARN}.get(state, DIM)
        note = it["note"] or ""
        if note:
            note = ellipsis(note, self.small, int((right - name_x) * 0.45))
        note_w = self.small.measure(note) + P(12) if note else 0
        name = ellipsis(it["path"].name, self.font,
                        right - name_x - note_w - P(8))
        self.create_text(name_x, y + rh / 2, anchor="w", text=name, fill=TEXT,
                         font=self.font)
        if note:
            self.create_text(right - P(2), y + rh / 2, anchor="e", text=note,
                             fill=state_col, font=self.small)

    def sel_targets(self) -> set[str]:
        """Targets shared by every selected row - used to highlight chips."""
        idx = self.selected() or list(range(len(self.items)))
        if not idx:
            return set()
        vals = {self.items[i].get("target") for i in idx if i < len(self.items)}
        return {v for v in vals if v}


# --------------------------------------------------------------------- app ---

def native_move(hwnd) -> None:
    """Unused fallback: hand the move to the compositor.

    Kept for reference only - Tk re-grabs the mouse right after the binding
    runs, which cancels DefWindowProc's move loop, so the title bar uses
    window_drag() below instead.
    """
    u = ctypes.windll.user32
    u.ReleaseCapture()
    u.SendMessageW(hwnd, 0x00A1, 0x0002, 0)


def window_rect(hwnd) -> tuple[int, int]:
    """Outer (screen) position of a window."""
    from ctypes import wintypes

    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top


def window_drag(hwnd, x: int, y: int) -> None:
    """Move a window natively (unused: Tk overrides this on its next flush)."""
    u = ctypes.windll.user32
    u.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0,
                   0x0001 | 0x0002 | 0x0004)  # NOSIZE | NOZORDER | NOACTIVATE


class App:
    W, H = 1060, 680

    def __init__(self, paths=None):
        _rr_cache.clear()
        SETTLERS.clear()
        PANELS.clear()
        from convall_settings import load_settings, THEMES
        self.preferences = load_settings()
        self.theme = self.preferences.get('theme', 'Dark+')
        if self.theme not in THEMES:
            self.theme = 'Dark+'
        self._set_palette(self.theme)
        self.root = self._make_root()
        self.root.withdraw()
        self.root.title("ConvAll")
        self.root.configure(bg=BG)
        try:
            if res("icon.ico").exists():
                self.root.iconbitmap(default=str(res("icon.ico")))
        except Exception:
            pass

        self.events: queue.Queue = queue.Queue()
        folder = self.preferences.get('output_folder')
        self.outdir = Path(folder) if isinstance(folder, str) and Path(folder).is_dir() else None
        self.last_input = self.preferences.get('input_folder', '')
        self.running = False
        self.cancel_flag = False
        self.chips: dict[str, Pill] = {}
        self.groups: dict[str, list[str]] = {}
        self._chip_job = None
        self._chip_w = 0
        self._chip_h = 0
        self._chip_sig = None
        self._last_size = (0, 0)
        self.opts: dict = {k: v["default"] for k, v in OPTIONS.items()}
        stored = self.preferences.get('options', {})
        if isinstance(stored, dict):
            from convall_engine import TEXT_OPTIONS
            self.opts.update({k: v for k, v in stored.items() if k in OPTIONS
                              and v in [value for _, value in OPTIONS[k]['choices']]})
        self._opt_chips: dict[str, dict] = {}

        self._fonts()
        self._build()
        self.list.on_pick = self.pick_files
        self._show_output()
        self._place_window()
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.after(20, self._apply_chrome)
        if self.dnd_lib:
            self.root.after(120, self._bind_dnd)
        self.root.after(60, self._pump)
        self.root.bind("<Return>", lambda _e: self.start())
        self.root.bind("<Escape>", lambda _e: self.cancel_or_clear())
        self.root.bind("<Control-o>", lambda _e: self.pick_files())
        self.root.bind("<Control-a>", lambda _e: self.select_all())
        self.root.bind("<Delete>", lambda _e: self.drop_selected())
        self.root.bind("<Configure>", self._on_root_conf)
        if paths:
            self.list.add(paths)
            self.status_lbl.configure(
                text=plural(len(self.list.items), "file") + " ready")

    # ---------------------------------------------------------- window ---
    @staticmethod
    def _set_palette(name):
        from convall_settings import THEMES
        global BG, PANEL, PANEL_HI, LINE, TEXT, MUTED, DIM, ACCENT, ACCENT_HI, ACCENT_SOFT
        BG, PANEL, PANEL_HI, LINE, TEXT, MUTED, DIM, ACCENT, ACCENT_HI, ACCENT_SOFT = THEMES[name]
        # Constructor defaults are evaluated at import time; update these too.
        for cls in (Pill, Panel, Progress, FileList, ScrollBox):
            defaults = cls.__init__.__kwdefaults__
            if defaults:
                if 'bg' in defaults:
                    defaults['bg'] = BG if cls is Panel else PANEL
                if 'fill' in defaults:
                    defaults['fill'] = PANEL if cls is Panel else PANEL_HI

    def _save_preferences(self):
        from convall_settings import save_settings
        try:
            save_settings({'theme': self.theme, 'options': self.opts,
                           'input_folder': self.last_input,
                           'output_folder': str(self.outdir) if self.outdir else None})
        except OSError as ex:
            self.status_lbl.configure(text=f'Could not save preferences: {ex}', fg=WARN)

    def change_theme(self, name):
        if self.running or self.ff_busy:
            self.status_lbl.configure(text='Change theme after the current task finishes')
            return
        items, selection = self.list.items, self.list.sel.copy()
        self.theme = name
        self._save_preferences()
        for job in (self._chip_job, RESIZE.get('job')):
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self._chip_job = None
        self._chip_sig = None
        self._chip_w = self._chip_h = 0
        SETTLERS.clear()
        PANELS.clear()
        RESIZE.update(active=False, job=None)
        for widget in self.root.winfo_children():
            widget.destroy()
        _rr_cache.clear()
        self.chips.clear()
        self._opt_chips.clear()
        self._set_palette(name)
        self.root.configure(bg=BG)
        self._build()
        self.list.items, self.list.sel = items, selection
        self.list.on_pick = self.pick_files
        self._show_output()
        self._on_queue_change()
        self._chrome()
        self.root.after(80, self._bind_dnd)

    def _make_root(self):
        try:
            from tkinterdnd2 import TkinterDnD
            self.dnd_lib = True
            return TkinterDnD.Tk()
        except Exception:
            self.dnd_lib = False
            return tk.Tk()

    def _chrome(self):
        """Let Windows own dragging, Snap, resize, maximize and restore."""
        try:
            u = ctypes.windll.user32
            hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_STYLE, WS_CAPTION = -16, 0x00C00000
            style = u.GetWindowLongW(hwnd, GWL_STYLE)
            native_style = style | WS_CAPTION | 0x00040000 | 0x00020000 | 0x00010000
            u.SetWindowLongW(hwnd, GWL_STYLE, native_style)
            u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED
            try:
                dwm = ctypes.windll.dwmapi
                on = ctypes.c_int(0 if self.theme in ('Light+', 'Solarized Light') else 1)
                dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
                rnd = ctypes.c_int(2)
                dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rnd), 4)
                border = ctypes.c_uint(0x00100b08)  # COLORREF 0x00BBGGRR = app background
                dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)
                caption = ctypes.c_uint(0x00100b08)
                dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
            except Exception:
                pass
            self.hwnd = hwnd
            return native_style != style
        except Exception:
            self.hwnd = None
            return False

    def _apply_chrome(self, tries=0):
        if self._chrome():
            try:  # client area grew when the caption left - pin it back
                w, h = P(self.W), P(self.H)
                self.root.geometry(f"{w}x{h}")
            except Exception:
                pass
        elif tries < 6:
            self.root.after(60, lambda: self._apply_chrome(tries + 1))

    def _place_window(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = P(self.W), P(self.H)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - P(20))
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(P(760), P(540))

    def _fonts(self):
        f = lambda n, w="normal": tkfont.Font(family="Segoe UI", size=-P(n),
                                              weight=w)
        self.f_body = f(12)
        self.f_small = f(11)
        self.f_tiny = f(10)
        self.f_label = f(10, "bold")
        self.f_title = f(14, "bold")
        self.f_head = f(13, "bold")
        self.f_cta = f(13, "bold")
        self.f_chip = f(11)
        self.f_mono = tkfont.Font(family="Consolas", size=-P(11))

    # ----------------------------------------------------------- build ---
    def _build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(1, weight=1)

        self._titlebar(r).grid(row=0, column=0, sticky="ew")

        body = tk.Frame(r, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=P(16))
        body.grid_columnconfigure(0, weight=1, uniform="c")
        body.grid_columnconfigure(1, weight=1, uniform="c")
        body.grid_rowconfigure(0, weight=1)

        self._queue_panel(body).grid(row=0, column=0, sticky="nsew",
                                     padx=(0, P(7)))
        self._target_panel(body).grid(row=0, column=1, sticky="nsew",
                                      padx=(P(7), 0))
        self._footer(r).grid(row=2, column=0, sticky="ew", padx=P(16),
                             pady=(0, P(14)))
        self._sync_cta()

    # title bar ---------------------------------------------------------
    def _titlebar(self, master):
        bar = tk.Frame(master, bg=BG)
        left = tk.Frame(bar, bg=BG)
        left.pack(side="left", padx=P(20), pady=P(18))

        try:  # the mark: drawn at its own size so it stays crisp, not downscaled
            size = P(30)
            logo = tk.Canvas(left, width=size, height=size, bg=BG, bd=0,
                             highlightthickness=0)
            logo.pack(side="left")
            logo.create_image(0, 0, anchor="nw",
                              image=rr(size, size, int(size * 0.28), ACCENT, BG))
            th = max(2, int(size * 0.115))
            top_y, bot_y = size * 0.35, size * 0.65
            # top arrow pointing right
            logo.create_line(size * 0.24, top_y, size * 0.62, top_y,
                             fill="white", width=th, capstyle="round")
            logo.create_polygon(size * 0.56, top_y - size * 0.145,
                                size * 0.56, top_y + size * 0.145,
                                size * 0.85, top_y, fill="white", outline="")
            # bottom arrow pointing left
            logo.create_line(size * 0.76, bot_y, size * 0.38, bot_y,
                             fill="white", width=th, capstyle="round")
            logo.create_polygon(size * 0.44, bot_y - size * 0.145,
                                size * 0.44, bot_y + size * 0.145,
                                size * 0.15, bot_y, fill="white", outline="")
        except Exception:  # fallback mark
            dot = tk.Canvas(left, width=P(22), height=P(22), bg=BG, bd=0,
                            highlightthickness=0)
            dot.pack(side="left")
            dot.create_image(0, 0, anchor="nw",
                             image=rr(P(22), P(22), P(7), ACCENT, BG))
            dot.create_text(P(11), P(12), text="⇄", fill="#ffffff",
                            font=tkfont.Font(family="Segoe UI", size=-P(12)))

        tk.Label(left, text="ConvAll", bg=BG, fg=TEXT, font=self.f_title
                 ).pack(side="left", padx=(P(9), P(8)))
        tk.Label(left, text="Convert locally. Keep your files private.", bg=BG, fg=MUTED,
                 font=self.f_small).pack(side="left")

        # Windows supplies the real caption buttons and Snap layouts.
        self.theme_button = Pill(bar, f'Theme: {self.theme} ▾', self.f_small,
                                 bg=BG, fill=PANEL, fg=TEXT, hover=PANEL_HI,
                                 command=self.toggle_theme_menu)
        self.theme_button.pack(side='right', padx=P(18))
        return bar

    def close_theme_menu(self):
        popup = getattr(self, '_theme_popup', None)
        self._theme_popup = None
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        binding = getattr(self, '_theme_outside_binding', None)
        if binding:
            self.root.unbind('<Button-1>', binding)
            self._theme_outside_binding = None

    def toggle_theme_menu(self):
        if getattr(self, '_theme_popup', None) is not None:
            self.close_theme_menu()
            return
        from convall_settings import THEMES
        popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(bg=LINE, padx=1, pady=1)
        popup.transient(self.root)
        self._theme_popup = popup
        for name in THEMES:
            def choose(n=name):
                self.close_theme_menu()
                self.change_theme(n)
            button = tk.Button(popup, text=('✓  ' if name == self.theme else '    ') + name,
                               anchor='w', bg=PANEL, fg=TEXT, activebackground=ACCENT,
                               activeforeground='white', relief='flat', bd=0,
                               padx=P(14), pady=P(7), font=self.f_small, command=choose)
            button.pack(fill='x')
        popup.update_idletasks()
        x = self.theme_button.winfo_rootx() + self.theme_button.winfo_width() - popup.winfo_reqwidth()
        y = self.theme_button.winfo_rooty() + self.theme_button.winfo_height() + P(5)
        popup.geometry(f'+{max(0, x)}+{max(0, y)}')
        popup.deiconify()
        popup.bind('<Escape>', lambda e: self.close_theme_menu())
        popup.bind('<FocusOut>', lambda e: self.root.after_idle(self._dismiss_unfocused_theme))
        def outside(event):
            if event.widget is not self.theme_button:
                self.close_theme_menu()
        self._theme_outside_binding = self.root.bind('<Button-1>', outside, add='+')
        popup.winfo_children()[0].focus_set()

    def _dismiss_unfocused_theme(self):
        popup = getattr(self, '_theme_popup', None)
        if popup is None:
            return
        focus = self.root.focus_get()
        # A click on Theme must reach its release handler before closing;
        # otherwise the release would immediately reopen the popover.
        if focus is None:
            self.close_theme_menu()

    def _on_root_conf(self, e):
        # <Configure> bubbles up from every child; only the window itself matters
        if e.widget is not self.root:
            return
        if (e.width, e.height) == self._last_size:
            return
        self._last_size = (e.width, e.height)
        note_resize(self.root)
        # the chip area is sized from the panel height, so re-fit it too
        self._queue_chip_layout()

    def _install_native_caption(self):
        """Make the custom title bar a real Windows non-client drag surface.

        Child HWNDs pass title-bar hit tests through to the outer window. This
        enters Windows' normal move loop before Tk grabs the mouse: no geometry
        calls, synthetic mouse messages, repaint loops or compositor waits.
        """
        from ctypes import wintypes

        common = ctypes.WinDLL("comctl32")
        result = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(
            result, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
            wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        common.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        common.DefSubclassProc.restype = result
        common.SetWindowSubclass.argtypes = [wintypes.HWND, proc_type,
                                             ctypes.c_size_t, ctypes.c_size_t]
        common.SetWindowSubclass.restype = wintypes.BOOL
        common.RemoveWindowSubclass.argtypes = [wintypes.HWND, proc_type,
                                                ctypes.c_size_t]

        def caption_proc(hwnd, msg, wp, lp, ident, data):
            if msg == 0x0084:  # WM_NCHITTEST, signed screen coordinates
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                try:
                    bar = self.root.grid_slaves(row=0)[0]
                    bx, by = bar.winfo_rootx(), bar.winfo_rooty()
                    inside = (bx <= x < bx + bar.winfo_width()
                              and by <= y < by + bar.winfo_height())
                    for button in (self.btn_min, self.btn_close):
                        if (button.winfo_rootx() <= x < button.winfo_rootx() + button.winfo_width()
                                and button.winfo_rooty() <= y < button.winfo_rooty() + button.winfo_height()):
                            inside = False
                    if inside:
                        return 2 if hwnd == self.hwnd else -1  # CAPTION / TRANSPARENT
                except tk.TclError:
                    pass
            if msg == 0x0082:  # WM_NCDESTROY
                common.RemoveWindowSubclass(hwnd, self._caption_proc, ident)
            return common.DefSubclassProc(hwnd, msg, wp, lp)

        self._caption_proc = proc_type(caption_proc)
        self._caption_api = common  # keep the DLL and callback alive
        bar = self.root.grid_slaves(row=0)[0]
        handles = {self.hwnd, self.root.winfo_id(), bar.winfo_id()}
        handles.update(w.winfo_id() for w in _descendants(bar)
                       if not isinstance(w, Pill))
        for hwnd in handles:
            if not common.SetWindowSubclass(hwnd, self._caption_proc, 1, 0):
                raise ctypes.WinError()

    def _drag_start(self, e):
        """Remember the cursor's offset inside the window."""
        self._dragging = True
        self._drag_off = (e.x_root - self.root.winfo_x(),
                          e.y_root - self.root.winfo_y())

    def _native_drag(self):
        if not self._dragging:
            return
        u = ctypes.windll.user32
        if not u.GetAsyncKeyState(0x01) & 0x8000:
            return
        u.ReleaseCapture()
        from ctypes import wintypes
        point = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(point))
        position = ((point.y & 0xFFFF) << 16) | (point.x & 0xFFFF)
        # Supply the actual screen point: zero makes Windows jump to (0, 0).
        u.SendMessageW(self.hwnd, 0x00A1, 2, position)
        self._dragging = False

    def _drag_move(self, e):
        if not getattr(self, "_dragging", False):
            return
        dx, dy = self._drag_off
        x, y = e.x_root - dx, e.y_root - dy
        if (x, y) == getattr(self, "_drag_last", None):
            return
        self._drag_last = (x, y)
        if not getattr(self, "_drag_preview", None):
            # Move only a hollow outline, not dozens of independently painted
            # child HWNDs. Commit the real window position once on release.
            preview = tk.Toplevel(self.root)
            preview.withdraw()
            preview.overrideredirect(True)
            preview.configure(bg="#010203")
            preview.attributes("-transparentcolor", "#010203")
            preview.attributes("-topmost", True)
            canvas = tk.Canvas(preview, bg="#010203", bd=0,
                               highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            w, h = self.root.winfo_width(), self.root.winfo_height()
            canvas.create_rectangle(2, 2, w - 3, h - 3, outline=ACCENT,
                                    width=P(2))
            preview.geometry(f"{w}x{h}{x:+d}{y:+d}")
            preview.deiconify()
            self._drag_preview = preview
        else:
            self._drag_preview.geometry(f"{x:+d}{y:+d}")

    def _drag_end(self, _e=None):
        self._dragging = False
        preview = getattr(self, "_drag_preview", None)
        if preview is not None:
            preview.destroy()
            self._drag_preview = None
            x, y = self._drag_last
            self.root.geometry(f"{x:+d}{y:+d}")

    # queue panel -------------------------------------------------------
    def _queue_panel(self, master):
        wrap = Panel(master, fill=PANEL, radius=13)
        f = wrap.inner
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x", padx=P(16), pady=(P(14), P(8)))
        tk.Label(head, text="QUEUE", bg=PANEL, fg=DIM, font=self.f_label
                 ).pack(side="left")
        self.count_lbl = tk.Label(head, text="0 files", bg=PANEL, fg=DIM,
                                  font=self.f_small)
        self.count_lbl.pack(side="left", padx=P(8))

        tools = tk.Frame(f, bg=PANEL)
        tools.pack(fill="x", padx=P(16), pady=(0, P(10)))

        self.btn_add = Pill(head, "+  Add files", self.f_small, bg=PANEL,
                            fill=ACCENT_SOFT, fg=TEXT, hover=PANEL_HI,
                            padx=12, pady=6, command=self.pick_files)
        self.btn_add.pack(side="right")
        self.btn_none = Pill(tools, "Deselect", self.f_small, bg=PANEL,
                             fill=PANEL_HI, fg=MUTED, hover="#232a36", padx=9,
                             pady=6, command=self.select_none)
        self.btn_none.pack(side="right", padx=(0, P(6)))
        self.btn_all = Pill(tools, "Select all", self.f_small, bg=PANEL,
                            fill=PANEL_HI, fg=MUTED, hover="#232a36", padx=9,
                            pady=6, command=self.select_all)
        self.btn_all.pack(side="right", padx=(0, P(6)))
        self.btn_clear = Pill(tools, "Clear queue", self.f_small, bg=PANEL,
                              fill=PANEL_HI, fg=MUTED, hover="#232a36", padx=10,
                              pady=6, command=self.clear_all)
        self.btn_clear.pack(side="right", padx=(0, P(6)))
        tk.Label(tools, text="FILE  /  STATUS", bg=PANEL, fg=DIM,
                 font=self.f_label).pack(side="left")

        self.list = FileList(f, bg=PANEL, on_change=self._on_queue_change,
                             on_open=self._open_row, on_hover=self._hover_row,
                             on_select=self._on_select)
        self.list.pack(fill="both", expand=True, padx=P(10), pady=(0, P(4)))
        tip = tk.Frame(f, bg=PANEL)
        tip.pack(fill="x", padx=P(18), pady=(0, P(10)))
        tk.Label(tip, text="Select files → choose a format. Ctrl / Shift for multiple.",
                 bg=PANEL, fg=MUTED,
                 font=self.f_tiny, anchor="w").pack(side="left")
        self.sel_lbl = tk.Label(tip, text="", bg=PANEL, fg=DIM,
                                font=self.f_tiny, anchor="e")
        self.sel_lbl.pack(side="right")
        return wrap

    # target panel ------------------------------------------------------
    def _target_panel(self, master):
        wrap = Panel(master, fill=PANEL, radius=13)
        f = wrap.inner
        head = tk.Frame(f, bg=PANEL)
        head.pack(fill="x", padx=P(16), pady=(P(14), P(2)))
        self.tco_head = head
        tk.Label(head, text="CONVERT TO", bg=PANEL, fg=DIM, font=self.f_label
                 ).pack(side="left")
        self.hint_lbl = tk.Label(head, text="", bg=PANEL, fg=DIM,
                                 font=self.f_small)
        self.hint_lbl.pack(side="right")

        # SAVE TO is pinned to the bottom; the chip grid above it scrolls
        out = tk.Frame(f, bg=PANEL)
        out.pack(side="bottom", fill="x", padx=P(16), pady=(P(6), P(14)))
        self.save_wrap = out
        tk.Label(out, text="SAVE TO", bg=PANEL, fg=DIM, font=self.f_label,
                 pady=P(1), anchor="w").pack(fill="x")
        row = tk.Frame(out, bg=PANEL)
        row.pack(fill="x", pady=(P(6), 0))
        self.out_lbl = tk.Label(row, text="Same folder as each file", bg=PANEL,
                                fg=MUTED, font=self.f_small, anchor="w")
        self.out_lbl.pack(side="left", fill="x", expand=True)
        self.btn_out = Pill(row, "Choose", self.f_small, bg=PANEL,
                            fill=PANEL_HI, fg=TEXT, hover="#222834", padx=11,
                            pady=5, command=self.pick_outdir)
        self.btn_out.pack(side="right")
        self.btn_open_out = Pill(row, 'Open ↗', self.f_small, bg=PANEL,
                                 fill=PANEL_HI, fg=TEXT, padx=10, pady=5,
                                 command=self.open_output)
        self.btn_open_out.pack(side='right', padx=(0, P(6)))
        self.btn_out_reset = Pill(row, "Reset", self.f_small, bg=PANEL,
                                  fill=PANEL, fg=MUTED, hover=PANEL_HI,
                                  padx=8, pady=5, command=self.reset_outdir)

        self.chip_scroll = ScrollBox(f, bg=PANEL, on_size=self._queue_chip_layout)
        # Small requested height on purpose: the packer then always has room for
        # OPTIONS and SAVE TO, and this fills whatever is left (and scrolls).
        self.chip_scroll.configure(height=P(150))
        self.chip_scroll.pack(fill="both", expand=True, padx=P(12), pady=(0, P(8)))
        self.grid_host = self.chip_scroll.inner
        self.grid_host.bind("<Configure>", self._queue_chip_layout)

        # OPTIONS is packed bottom like SAVE TO, so the packer always reserves
        # its space and the chip grid absorbs whatever is left (and scrolls).
        self.opt_wrap = tk.Frame(f, bg=PANEL)
        self.opt_wrap.pack(side="bottom", fill="x", padx=P(16),
                           pady=(P(4), P(2)))
        self.opt_sep = tk.Frame(self.opt_wrap, bg="#1d2530", height=P(1))
        self.opt_sep.pack(fill="x", pady=(0, P(8)))
        self.opt_head = tk.Frame(self.opt_wrap, bg=PANEL)
        self.opt_head.pack(fill="x")
        self.opt_title = tk.Label(self.opt_head, text="OPTIONS", bg=PANEL,
                                  fg=DIM, font=self.f_label, pady=P(1))
        self.opt_title.pack(side="left")
        self.opt_target = tk.Label(self.opt_head, text="", bg=PANEL, fg=DIM,
                                   font=self.f_tiny)
        self.opt_target.pack(side="left", padx=P(6))
        self.opt_host = tk.Frame(self.opt_wrap, bg=PANEL)
        self.opt_host.pack(fill="x", pady=(P(2), 0))
        return wrap

    # footer ------------------------------------------------------------
    def _footer(self, master):
        f = tk.Frame(master, bg=BG)
        f.grid_columnconfigure(1, weight=1)
        self.btn_go = Pill(f, "Convert", self.f_cta, bg=BG, fill=ACCENT,
                           fg="#ffffff", hover=ACCENT_HI, radius=10,
                           padx=26, pady=11, min_width=180,
                           command=self.start)
        self.btn_go.grid(row=0, column=0, rowspan=2, sticky="w", pady=(P(12), 0))

        self.progress = Progress(f, bg=BG, height=5)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(P(18), P(14)),
                           pady=(P(18), 0))
        self.status_lbl = tk.Label(f, text="Ready", bg=BG, fg=MUTED,
                                   font=self.f_small, anchor="w")
        self.status_lbl.grid(row=1, column=1, sticky="ew",
                             padx=(P(18), P(14)), pady=(P(4), P(12)))

        self.engine_lbl = tk.Label(f, text="", bg=BG, fg=DIM, font=self.f_tiny)
        self.engine_lbl.grid(row=0, column=2, rowspan=2, sticky="e",
                             pady=(P(10), 0))
        self.engine_lbl.bind("<Button-1>", self._toggle_ffmpeg_strip)
        self.engine_lbl.configure(cursor="hand2")

        # the ffmpeg strip: appears only when audio/video have no engine
        self.ff_busy = False
        strip = tk.Frame(f, bg=BG)
        strip.grid(row=2, column=0, columnspan=3, sticky="ew",
                   pady=(P(2), P(10)))
        strip.grid_columnconfigure(0, weight=1, minsize=P(120))
        self.ff_strip = strip
        tk.Label(strip, text="audio, video and gif need ffmpeg — one-time "
                            "download, then it lives next to the app",
                 bg=BG, fg="#8a5a3a", font=self.f_small, anchor="w"
                 ).grid(row=0, column=0, sticky="w")
        self.ff_msg = tk.Label(strip, text="", bg=BG, fg=MUTED,
                               font=self.f_small, anchor="e")
        self.ff_msg.grid(row=0, column=1, sticky="e", padx=(P(8), P(10)))
        self.ff_btn = Pill(strip, "Download ffmpeg (~110 MB)", self.f_small,
                           bg=BG, fill="#7a4a2a", fg="#ffd9bd",
                           hover="#8d5733", padx=12, pady=6,
                           command=self._download_ffmpeg)
        self.ff_btn.grid(row=0, column=2, sticky="e")
        self.ff_prog = Progress(strip, bg=BG, height=4)
        self.ff_prog.grid(row=1, column=0, columnspan=3, sticky="ew",
                          pady=(P(8), 0))
        if not self._check_engine():
            strip.grid()
        else:
            strip.grid_remove()
        # the strip changes the footer height, so the chip area must re-fit
        self.root.after(40, self._queue_chip_layout)
        return f

    def _check_engine(self):
        from convall_engine import ffmpeg
        try:
            ffmpeg()
            self.engine_lbl.configure(text="● ffmpeg ready", fg="#2e6b52",
                                      cursor="")
            if getattr(self, "ff_strip", None) is not None:
                self.ff_strip.grid_remove()
            return True
        except ConvertError:
            self.engine_lbl.configure(
                text="● audio & video need ffmpeg — click to fix",
                fg="#8a5a3a", cursor="hand2")
            return False

    def _toggle_ffmpeg_strip(self, _e=None):
        if self._check_engine():
            self.status_lbl.configure(text="ffmpeg is installed — all formats "
                                           "available", fg=OK)
            return
        if self.ff_strip.winfo_ismapped():
            self.ff_strip.grid_remove()
        else:
            self.ff_strip.grid()

    def _download_ffmpeg(self):
        if self.ff_busy:
            return
        self.ff_busy = True
        self.ff_btn.configure_pill(text="Downloading…", enabled=False)
        self.ff_msg.configure(text="0%", fg=MUTED)

        def prog(got, total):
            self.events.put(("ffprog", got, total))

        def work():
            from convall_engine import download_ffmpeg
            try:
                path = download_ffmpeg(prog)
                self.events.put(("ffdone", path, None))
            except Exception as ex:
                self.events.put(("fferr", str(ex), None))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ chips ---
    def _layout_chips(self):
        host = self.grid_host
        width = host.winfo_width()
        if width < P(60):
            return
        panel_h = self.opt_wrap.master.winfo_height()
        if (abs(width - getattr(self, "_chip_w", 0)) < P(20)
                and panel_h == getattr(self, "_chip_h", 0)
                and self.chips and self._chip_key() == self._chip_sig):
            return
        self._chip_w, self._chip_sig, self._chip_h = width, self._chip_key(), panel_h
        self._build_chips(width)

    def _chip_key(self):
        return tuple((g, tuple(v)) for g, v in self.groups.items())

    def _queue_chip_layout(self, event=None):
        """Rebuild the chip grid once the window stops changing size."""
        if self._chip_job:
            try:
                self.root.after_cancel(self._chip_job)
            except Exception:
                pass
        self._chip_job = self.root.after(120, self._layout_chips_now)

    def _layout_chips_now(self):
        self._chip_job = None
        self._chip_sig = None      # force a rebuild against the new height
        self._layout_chips()

    def _build_chips(self, width):
        host = self.grid_host
        for w in host.winfo_children():
            w.destroy()
        self.chips.clear()
        if not self.groups:
            tk.Label(host,
                     text="Add or drop files on the left and every format\n"
                          "they can become appears here",
                     bg=PANEL, fg=DIM, font=self.f_small, justify="center"
                     ).place(relx=0.5, rely=0.35, anchor="center")
            host.configure(height=P(150))
            self.hint_lbl.configure(text="")
            return
        x = y = 0
        gap_x, gap_y = P(6), P(6)
        line = self.f_label.metrics("linespace")
        used = 0
        for g in GROUP_ORDER:
            fmts = self.groups.get(g)
            if not fmts:
                continue
            if x > 0:
                x, y = 0, y + gap_y
            lab = tk.Label(host, text=GROUP_LABEL.get(g, g.upper()), bg=PANEL,
                           fg=DIM, font=self.f_label, anchor="w")
            lab.place(x=x, y=y, height=line + P(2))
            y += line + P(4)
            x = 0
            for fmt in fmts:
                chip = Pill(host, fmt, self.f_chip, bg=PANEL, fill=PANEL_HI,
                            fg="#cbd5e3", hover="#242b38", padx=11, pady=5,
                            command=lambda t=fmt: self.set_target(t))
                cw = chip.winfo_reqwidth()
                if x + cw > width and x > 0:
                    x = 0
                    y += chip.winfo_reqheight() + gap_y
                chip.place(x=x, y=y)
                self.chips[fmt] = chip
                x += cw + gap_x
            y += (self.chips[fmts[-1]].winfo_reqheight() if fmts else 0) + P(10)
            used = y
        # placed children never size a frame - state the height ourselves
        host.configure(height=max(P(60), used))
        self.hint_lbl.configure(text=f"{len(self.chips)} formats")
        self._sync_chips()

    def _sync_chips(self):
        active = self.list.sel_targets()
        for fmt, chip in self.chips.items():
            chip.configure_pill(selected=(fmt in active))

    def set_target(self, fmt):
        """A chip click: assign this format to the selected rows (or all)."""
        rows = (self.list.sel or set(range(len(self.list.items))))
        if rows and all(ext_of(self.list.items[i]["path"]) == fmt
                        for i in rows if i < len(self.list.items)):
            self.status_lbl.configure(
                text=f"already {fmt} — pick a different format", fg=MUTED)
            return
        done, skipped = self.list.assign(fmt)
        if not done:
            self.status_lbl.configure(
                text=f"None of these rows can become {label_of(fmt)}", fg=WARN)
        elif skipped:
            self.status_lbl.configure(
                text=f"{label_of(fmt)} set for {done} of {done + skipped} rows "
                     f"— the rest can't make it", fg=MUTED)
        else:
            self.status_lbl.configure(
                text=f"{label_of(fmt)} set for {plural(done, 'row')}", fg=MUTED)
        self._sync_cta()

    def select_all(self):
        self.list.select_all()

    def select_none(self):
        self.list.select_none()

    def drop_selected(self):
        if self.running:
            return
        for i in sorted(self.list.sel, reverse=True):
            self.list.remove(i)

    def _option_keys(self) -> tuple[list[str], str]:
        """Which knobs to show, and which format they belong to."""
        rows = [it for it in self.list.items if it.get("target")]
        if self.list.sel:
            picked = [self.list.items[i] for i in self.list.sel
                      if i < len(self.list.items) and
                      self.list.items[i].get("target")]
            if picked:
                rows = picked
        if not rows:
            return [], ""
        targets = {it["target"] for it in rows}
        if len(targets) == 1:
            t = next(iter(targets))
            kinds = {kind_of(it["path"]) for it in rows}
            kind = next(iter(kinds)) if len(kinds) == 1 else ""
            return options_for(t, kind), label_of(t)
        keys: set[str] | None = None
        for it in rows:
            k = set(options_for(it["target"], kind_of(it["path"])))
            keys = k if keys is None else keys & k
        ordered = [k for k in OPTIONS if k in (keys or set())]
        return ordered, "mixed"

    def _build_options(self):
        from convall_engine import metadata_fields
        keys, target_label = self._option_keys()
        rows = [self.list.items[i] for i in (self.list.sel or range(len(self.list.items)))
                if self.list.items[i].get('target')]
        self._advanced_fields = (set.intersection(*(set(metadata_fields(r['target'])) for r in rows))
                                 if rows else set())
        for w in self.opt_host.winfo_children():
            w.destroy()
        self._opt_chips = {}
        if not keys and not rows:
            self.opt_wrap.pack_forget()
            return
        self.opt_wrap.pack(side="bottom", fill="x", padx=P(16),
                           pady=(P(4), P(2)))
        self.opt_target.configure(
            text=f"for {target_label}" if target_label else "")
        label_w = P(78)
        heights = [source_height(p) for p in self.list.active_paths()]
        known = [h for h in heights if h]
        ceiling = min(known) if known else None
        for key in keys:
            if key in ('fps', 'sample_rate', 'channels', 'strip_metadata'):
                continue
            spec = OPTIONS[key]
            row = tk.Frame(self.opt_host, bg=PANEL)
            row.pack(fill="x", pady=(0, P(4)))
            row.grid_columnconfigure(0, minsize=label_w)
            tk.Label(row, text=spec["label"], bg=PANEL, fg="#5c6779",
                     font=self.f_tiny, anchor="w"
                     ).grid(row=0, column=0, sticky="w")
            holder = tk.Frame(row, bg=PANEL)
            holder.grid(row=0, column=1, sticky="w")
            current = option_value(self.opts, key)
            if key in ("max_h", "video_height") and ceiling and current > ceiling:
                self.opts[key] = current = 0
            for text, value in spec["choices"]:
                chip = Pill(holder, text, self.f_tiny, bg=PANEL,
                            fill=PANEL_HI, fg="#c2cdda", hover="#242b38",
                            padx=8, pady=3, sel_fill="#2b4a7d",
                            command=lambda k=key, v=value: self.set_option(k, v))
                enabled = not (key in ("max_h", "video_height")
                               and ceiling and value > ceiling)
                chip.configure_pill(selected=(value == current), enabled=enabled)
                chip.pack(side="left", padx=(0, P(4)))
                self._opt_chips.setdefault(key, {})[value] = chip
        Pill(self.opt_host, 'Advanced / file name / metadata…', self.f_small,
             bg=PANEL, fill=PANEL_HI, fg=TEXT, command=self.advanced_options,
             pady=5).pack(anchor='w', pady=P(4))
        self.opt_wrap.update_idletasks()

    def advanced_options(self):
        from convall_engine import TEXT_OPTIONS
        self.close_theme_menu()
        selected = [self.list.items[i] for i in sorted(self.list.sel)
                    if i < len(self.list.items)]
        if not selected:
            self.status_lbl.configure(text='Select one or more rows before opening advanced settings.', fg=WARN)
            return
        existing = getattr(self, '_advanced_dialog', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        keys, _ = self._option_keys()
        initial = dict(self.opts)
        initial.update(selected[0].get('options', {}))
        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        self._advanced_dialog = dialog
        dialog.title('Conversion settings')
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        tk.Label(dialog, text='Advanced conversion settings', bg=PANEL, fg=TEXT,
                 font=self.f_head, anchor='w').pack(fill='x', padx=P(18), pady=(P(16), P(4)))
        tk.Label(dialog, text=f'Applies to {plural(len(selected), "selected file")}. Other rows stay unchanged.',
                 bg=PANEL, fg=MUTED, font=self.f_small, anchor='w').pack(fill='x', padx=P(18), pady=(0, P(12)))
        all_rows = tk.BooleanVar(value=False)
        tk.Checkbutton(dialog, text='Apply to all queued files instead', variable=all_rows,
                       bg=PANEL, fg=TEXT, selectcolor=BG, activebackground=PANEL,
                       activeforeground=TEXT).pack(anchor='w', padx=P(18), pady=(0, P(8)))
        entries = {}
        for key, label in TEXT_OPTIONS.items():
            if key not in self._advanced_fields:
                continue
            row = tk.Frame(dialog, bg=PANEL)
            row.pack(fill='x', padx=P(18), pady=P(4))
            tk.Label(row, text=label, bg=PANEL, fg=TEXT, width=16, anchor='w').pack(side='left')
            value = tk.StringVar(value=initial.get(key, ''))
            tk.Entry(row, textvariable=value, bg=BG, fg=TEXT, insertbackground=TEXT,
                     relief='flat', width=34).pack(side='left', ipady=P(4))
            entries[key] = value
        for key in ('fps', 'sample_rate', 'channels', 'strip_metadata'):
            if key not in keys:
                continue
            row = tk.Frame(dialog, bg=PANEL)
            row.pack(fill='x', padx=P(18), pady=P(4))
            tk.Label(row, text=OPTIONS[key]['label'], bg=PANEL, fg=TEXT,
                     width=16, anchor='w').pack(side='left')
            value = tk.StringVar(value=str(option_value(initial, key)))
            entries[key] = value
            for label, option in OPTIONS[key]['choices']:
                tk.Radiobutton(row, text=label, variable=value, value=str(option),
                               bg=PANEL, fg=TEXT, selectcolor=BG,
                               activebackground=PANEL).pack(side='left')
        def close():
            dialog.grab_release()
            self._advanced_dialog = None
            dialog.destroy()
        def apply():
            changes = {}
            for key, value in entries.items():
                raw = value.get()
                changes[key] = (next(v for _, v in OPTIONS[key]['choices'] if str(v) == raw)
                                   if key in OPTIONS else raw.strip())
            self.apply_row_options(selected, changes, all_rows.get())
            close()
        actions = tk.Frame(dialog, bg=PANEL)
        actions.pack(fill='x', padx=P(18), pady=P(16))
        Pill(actions, 'Apply settings', self.f_body, bg=PANEL, fill=ACCENT,
             fg='white', command=apply).pack(side='right')
        Pill(actions, 'Cancel', self.f_body, bg=PANEL, fill=PANEL_HI,
             fg=TEXT, command=close).pack(side='right', padx=P(8))
        dialog.protocol('WM_DELETE_WINDOW', close)
        dialog.bind('<Escape>', lambda e: (close(), 'break')[1])
        dialog.bind('<Return>', lambda e: (apply(), 'break')[1])
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        dialog.geometry(f'{width}x{height}+{max(0, x)}+{max(0, y)}')
        dialog.deiconify()
        dialog.grab_set()
        fields = [w for w in _descendants(dialog) if isinstance(w, tk.Entry)]
        (fields[0] if fields else dialog).focus_set()

    def apply_row_options(self, selected, changes, all_rows=False):
        rows = self.list.items if all_rows else selected
        count = 0
        for row in rows:
            if any(row is queued for queued in self.list.items):
                row.setdefault('options', {}).update(changes)
                count += 1
        self.status_lbl.configure(text=f'Advanced settings applied to {plural(count, "file")}.', fg=MUTED)

    def row_options(self, row):
        return {**self.opts, **row.get('options', {})}

    def set_option(self, key: str, value):
        self.opts[key] = value
        self._save_preferences()
        for v, chip in self._opt_chips.get(key, {}).items():
            chip.configure_pill(selected=(v == value))
        spec = OPTIONS[key]
        self.status_lbl.configure(
            text=f"{spec['label'].lower()} set to "
                 f"{dict((str(v), t) for t, v in spec['choices']).get(str(value), value)}",
            fg=MUTED)

    def _on_select(self):
        self._refresh_targets()

    def _refresh_targets(self):
        files = self.list.active_paths()
        self.groups = targets_grouped(files)
        self._build_options()      # first: the chip area sizes around it
        self._layout_chips()
        # A selection/assignment can change without changing the layout key.
        # Cached layout must never mean cached selection state.
        self._sync_chips()
        self._sync_cta()
        n_sel = len(self.list.sel)
        total = len(self.list.items)
        if n_sel:
            self.sel_lbl.configure(text=f"{n_sel} selected")
        elif total:
            self.sel_lbl.configure(text="all rows")
        else:
            self.sel_lbl.configure(text="")
        ready = sum(1 for i in self.list.items if i.get("target"))
        if not self.running:
            if not total:
                self.status_lbl.configure(text="Ready", fg=MUTED)
            elif not ready:
                self.status_lbl.configure(
                    text="Click a row, then pick a format on the right  →",
                    fg=MUTED)
            else:
                self.status_lbl.configure(
                    text=f"{ready} of {total} rows set", fg=MUTED)

    # ------------------------------------------------------------ state ---
    def _on_queue_change(self):
        n = len(self.list.items)
        self.count_lbl.configure(text="1 file" if n == 1 else f"{n} files")
        self._refresh_targets()
        if not self.running:
            ready = sum(1 for i in self.list.items if i.get("target"))
            if n and not ready:
                self.status_lbl.configure(
                    text="Pick a format on the right to fill the rows  →",
                    fg=MUTED)
            elif not n:
                self.status_lbl.configure(text="Ready", fg=MUTED)

    def _sync_cta(self):
        rows = [i for i in self.list.items if i.get("target")]
        ready, total = len(rows), len(self.list.items)
        if not total:
            self.btn_go.configure_pill(enabled=False, text="Convert")
        elif not ready:
            self.btn_go.configure_pill(enabled=False, text="Pick a format")
        else:
            same = {i["target"] for i in rows}
            of = f" of {total}" if ready < total else ""
            if len(same) == 1:
                text = f"Convert {ready}{of} → {label_of(rows[0]['target'])}"
            else:
                text = f"Convert {ready}{of} file" + ("s" if ready > 1 else "")
            self.btn_go.configure_pill(enabled=True, text=text)

    def pick_files(self):
        from tkinter import filedialog
        sel = filedialog.askopenfilenames(title="Pick files to convert",
                                          initialdir=self.last_input or None)
        if sel:
            self.last_input = str(Path(sel[0]).parent)
            self._save_preferences()
        if sel and self.list.add(sel):
            self.status_lbl.configure(
                text=plural(len(sel), "file") + " added")

    def pick_outdir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Where should files go?",
                                    initialdir=str(self.outdir) if self.outdir else self.last_input or None)
        if d:
            self.outdir = Path(d)
            self.out_lbl.configure(text=ellipsis(str(self.outdir), self.f_small,
                                                 self.out_lbl.winfo_width() or P(200)),
                                   fg=TEXT)
            self.btn_out_reset.pack(side="right", padx=(0, P(6)))
            self._save_preferences()

    def _show_output(self):
        if self.outdir:
            self.out_lbl.configure(text=ellipsis(str(self.outdir), self.f_small, P(240)), fg=TEXT)
            self.btn_out_reset.pack(side='right', padx=(0, P(6)))

    def open_output(self):
        folder = self.outdir
        if folder is None and self.list.items:
            indices = self.list.selected()
            folder = self.list.items[indices[0] if indices else 0]['path'].parent
        if folder is None:
            self.status_lbl.configure(text='Choose an output folder or add a file first', fg=MUTED)
            return
        try:
            os.startfile(str(folder))
        except OSError as ex:
            self.status_lbl.configure(text=f'Could not open folder: {ex}', fg=WARN)

    def reset_outdir(self):
        self.outdir = None
        self.out_lbl.configure(text="Same folder as each file", fg=MUTED)
        self.btn_out_reset.pack_forget()
        self._save_preferences()

    def clear_all(self):
        if self.running:
            return
        self.list.clear()
        self.status_lbl.configure(text="Ready", fg=MUTED)

    def cancel_or_clear(self):
        if self.running:
            self.cancel_flag = True
            self.btn_go.configure_pill(text="Stopping…")
            self.status_lbl.configure(text="Stopping after the current file…")
        else:
            self.clear_all()

    def _open_row(self, idx):
        p = self.list.items[idx]["path"]
        try:
            os.startfile(str(p.parent))  # type: ignore[attr-defined]
        except Exception:
            pass

    def _hover_row(self, idx):
        """Show the full text of a truncated row note in the status bar."""
        if self.running or idx is None:
            return
        note = self.list.items[idx].get("note", "")
        if note:
            self.status_lbl.configure(text=note, fg=MUTED)

    # -------------------------------------------------------------- dnd ---
    def _bind_dnd(self):
        if not self.dnd_lib:
            return
        from tkinterdnd2 import DND_FILES
        for w in (self.root, self.list, self.grid_host):
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _on_drop(self, e):
        paths = self.root.tk.splitlist(e.data)
        n = self.list.add(paths)
        self.status_lbl.configure(text=plural(n, "file") + " added")

    # ----------------------------------------------------------- convert ---
    def start(self):
        if self.running:
            self.cancel_flag = True
            self.btn_go.configure_pill(text="Stopping…")
            return
        jobs = [(i, it["path"], it["target"], self.row_options(it))
                for i, it in enumerate(self.list.items) if it.get("target")]
        if not jobs:
            self.status_lbl.configure(
                text="No row has a format yet — click a row, then a format")
            return
        skipped = len(self.list.items) - len(jobs)
        self.running, self.cancel_flag = True, False
        self.btn_go.configure_pill(text="Stop", fill="#8f2d3a", hover="#a83a48")
        self.progress.set(0, len(jobs))
        for i, _p, _t, _opts in jobs:
            self.list.set_state(i, "queued", "waiting")
        mix = len({t for _i, _p, t, _opts in jobs}) > 1
        self.status_lbl.configure(
            text=f"Converting {plural(len(jobs), 'file')}"
                 + (" to their own formats…" if mix else f" to {jobs[0][2]}…")
                 + (f"  ({skipped} row(s) without a format left alone)"
                    if skipped else ""),
            fg=MUTED)
        threading.Thread(target=self._worker,
                         args=(jobs, self.outdir, dict(self.opts)),
                         daemon=True).start()

    def _worker(self, jobs, outdir, opts):
        done = 0
        for step, (i, src, target, row_opts) in enumerate(jobs):
            if self.cancel_flag:
                self.events.put(("state", i, "cancelled", "stopped"))
                continue
            self.events.put(("state", i, "converting", "…"))
            if ext_of(src) == target:
                done += 1
                self.events.put(("state", i, "ok", f"already .{target}"))
                self.events.put(("tick", step + 1))
                continue
            try:
                outs = convert(src, target, outdir, row_opts)
                done += 1
                self.events.put(("state", i, "ok",
                                 "done" if len(outs) == 1
                                 else plural(len(outs), "file")))
                self.events.put(("log", f"{src.name} → "
                                        f"{', '.join(o.name for o in outs)}"))
            except Exception as ex:
                msg = str(ex).strip() or ex.__class__.__name__
                self.events.put(("state", i, "failed", msg))
                self.events.put(("log", f"{src.name}: {msg}"))
            self.events.put(("tick", step + 1))
        self.events.put(("done", done, len(jobs)))

    def _pump(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "state":
                    self.list.set_state(ev[1], ev[2], ev[3])
                elif kind == "tick":
                    self.progress.set(ev[1], self.progress.max_)
                elif kind == "log":
                    self.status_lbl.configure(text=ev[1], fg=MUTED)
                elif kind == "ffprog":
                    got, total = ev[1], ev[2] or 1
                    self.ff_prog.set(got, total)
                    self.ff_msg.configure(
                        text=f"{got / 1048576:.0f} / {total / 1048576:.0f} MB"
                             if total > 1 else f"{got / 1048576:.0f} MB")
                elif kind == "ffdone":
                    self.ff_busy = False
                    self.ff_prog.set(0, 1)
                    self.ff_btn.configure_pill(text="Download ffmpeg",
                                               enabled=True)
                    self.ff_msg.configure(text="")
                    self.ff_strip.grid_remove()
                    self._check_engine()
                    self.status_lbl.configure(
                        text="ffmpeg installed — audio, video and gif unlocked",
                        fg=OK)
                elif kind == "fferr":
                    self.ff_busy = False
                    self.ff_prog.set(0, 1)
                    self.ff_btn.configure_pill(
                        text="Retry download", enabled=True)
                    self.ff_msg.configure(text="download failed", fg=ERR)
                    self.status_lbl.configure(text=str(ev[1])[:150], fg=WARN)
                elif kind == "done":
                    ok, total = ev[1], ev[2]
                    self.running = False
                    self.btn_go.configure_pill(
                        fill=ACCENT, hover=ACCENT_HI, enabled=True)
                    self._sync_cta()
                    if self.cancel_flag:
                        self.status_lbl.configure(text="Stopped")
                    elif ok == total:
                        self.status_lbl.configure(
                            text=f"Done — {plural(ok, 'file')} converted", fg=OK)
                    else:
                        self.status_lbl.configure(
                            text=f"{ok} converted, {total - ok} failed", fg=WARN)
        except queue.Empty:
            pass
        self.root.after(90, self._pump)


def run(paths=None):
    App(paths).root.mainloop()


if __name__ == "__main__":
    run()
