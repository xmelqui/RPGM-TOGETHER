"""Click-through windows drawn on top of the game: the status bubble and viewers' pings.

They're separate always-on-top windows (works for every engine without touching
the game), so they show up when the host shares their screen on Discord. They
only show while the game is focused, and RPGMT blanks them out before OCR.
"""
import ctypes
import random
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import winutil
from .winutil import user32

KEY = "#ff00fe"  # transparent color key
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
MARGIN = 10
WAIT_COLOR, DONE_COLOR = "#f2b84b", "#3ecf8e"

user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetParent.restype = ctypes.c_void_p


def make_click_through(win):
    win.update_idletasks()
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                          | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)


PING_LIFE = 2.5      # seconds a ping stays on screen
EMOTE_LIFE = 2.2
CHAT_LIFE = 12.0     # seconds a chat message stays on the host's screen
CHAT_LINES = 5
STROKE_LIFE = 3.0      # seconds a drawing stays after the viewer lets go of the mouse
STROKE_STALE = 15.0    # a drawing that never got finished (viewer left) disappears after this
MAX_STROKE_POINTS = 6000     # all drawings on screen together (redrawn ~30x a second)
MAX_STROKES_PER_PLAYER = 3   # lines one viewer can have on screen at once
STACK_DIST = 0.05    # pings this close (fraction of the game screen) stack into one counter
FRAME_MS = 33


class PingLayer:
    """Viewers' pings and emotes drawn over the game window (and so on the stream)."""

    def __init__(self, root, get_hwnd):
        self.get_hwnd = get_hwnd
        self.pings = []    # dicts: x, y (0..1), name, color, count, born
        self.emotes = []   # dicts: emoji, x (0..1), born
        self.chat = []     # dicts: name, color, text, born
        self.chat_enabled = True
        self.strokes = {}  # (player id, stroke id) -> dict: name, color, points [(x, y)], done_at, at
        self.boxes = []    # on-screen rects of what's drawn, so OCR can ignore them
        self._images = {}  # emoji -> PhotoImage
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(self.win, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._styled = False
        self._rect = None
        self.win.after(FRAME_MS, self._tick)

    def add_ping(self, name, color, x, y):
        now = time.monotonic()
        for p in self.pings:
            if abs(p["x"] - x) < STACK_DIST and abs(p["y"] - y) < STACK_DIST:
                p["count"] += 1
                p["born"] = now
                # Each name once, most recent last: "x70 manolo", not "manolo, manolo, manolo".
                if name in p["names"]:
                    p["names"].remove(name)
                p["names"].append(name)
                return
        self.pings.append({"x": x, "y": y, "names": [name], "color": color, "count": 1, "born": now})

    def add_stroke(self, pid, name, color, stroke_id, points, done):
        now = time.monotonic()
        key = (pid, stroke_id)
        st = self.strokes.get(key)
        if st is None:
            mine = [k for k in self.strokes if k[0] == pid]
            if len(mine) >= MAX_STROKES_PER_PLAYER:  # this viewer's oldest line makes room
                self.strokes.pop(mine[0])
            st = self.strokes[key] = {"name": name, "color": color, "points": [], "done_at": None, "at": now}
        st["points"].extend(points)
        total = sum(len(v["points"]) for v in self.strokes.values())
        while total > MAX_STROKE_POINTS and len(self.strokes) > 1:  # too much ink: oldest lines go first
            oldest = next(iter(self.strokes))
            total -= len(self.strokes.pop(oldest)["points"])
        if total > MAX_STROKE_POINTS:
            del st["points"][: total - MAX_STROKE_POINTS]
        st["at"] = now
        if done:
            st["done_at"] = now

    def add_chat(self, name, color, text):
        self.chat = (self.chat + [{"name": name, "color": color, "text": text, "born": time.monotonic()}])[-CHAT_LINES:]

    def add_emote(self, name, color, emoji):
        self.emotes.append({"emoji": emoji, "name": name, "color": color,
                            "x": random.uniform(0.55, 0.9), "born": time.monotonic()})

    def _emoji_image(self, emoji, size):
        key = (emoji, size)
        if key not in self._images:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            try:
                font = ImageFont.truetype("seguiemj.ttf", int(size * 0.7))
                ImageDraw.Draw(img).text((size / 2, size / 2), emoji, font=font, anchor="mm",
                                         embedded_color=True)
            except OSError:
                pass
            # The color-key window has no partial transparency: put the emoji on a solid badge.
            badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(badge).ellipse((0, 0, size - 1, size - 1), fill=(20, 18, 31, 255))
            badge.alpha_composite(img)
            alpha = badge.getchannel("A").point(lambda a: 255 if a > 128 else 0)
            badge.putalpha(alpha)
            bg = Image.new("RGB", (size, size), KEY)
            bg.paste(badge, mask=alpha)
            self._images[key] = ImageTk.PhotoImage(bg)
        return self._images[key]

    def _tick(self):
        try:
            self._draw()
        finally:
            self.win.after(FRAME_MS, self._tick)

    def _draw(self):
        now = time.monotonic()
        self.pings = [p for p in self.pings if now - p["born"] < PING_LIFE]
        self.emotes = [e for e in self.emotes if now - e["born"] < EMOTE_LIFE]
        self.chat = [m for m in self.chat if now - m["born"] < CHAT_LIFE]
        self.strokes = {k: v for k, v in self.strokes.items() if not stroke_expired(v, now)}
        chat = self.chat if self.chat_enabled else []
        hwnd = self.get_hwnd()
        rect = winutil.client_rect_on_screen(hwnd) if hwnd else None
        if (not self.pings and not self.emotes and not chat and not self.strokes) or not rect or not winutil.is_foreground(hwnd):
            self.boxes = []
            self.win.withdraw()
            return
        l, t, r, b = rect
        w, h = r - l, b - t
        if rect != self._rect:
            self._rect = rect
            self.win.geometry(f"{w}x{h}+{l}+{t}")
        self.win.deiconify()
        if not self._styled:
            make_click_through(self.win)
            self._styled = True

        c = self.canvas
        c.delete("all")
        boxes = []
        unit = max(10, h // 40)
        font = ("Segoe UI", -max(12, h // 36), "bold")
        for p in self.pings:
            age = now - p["born"]
            x, y = p["x"] * w, p["y"] * h
            grow = min(1.0, age / 0.35)
            radius = unit * (0.6 + 1.4 * grow)
            # Expanding ring + dot, then a pulse ring every 0.8 s while it lives.
            c.create_oval(x - radius, y - radius, x + radius, y + radius, outline=p["color"], width=3)
            pulse = (age % 0.8) / 0.8
            pr = unit * (0.5 + 2.2 * pulse)
            c.create_oval(x - pr, y - pr, x + pr, y + pr, outline=p["color"], width=1)
            c.create_oval(x - unit * 0.3, y - unit * 0.3, x + unit * 0.3, y + unit * 0.3,
                          fill=p["color"], outline="#14121f", width=2)
            label = p["names"][-1] if p["count"] == 1 else f"×{p['count']}  {', '.join(p['names'][-3:])}"
            tid = c.create_text(x + radius + 6, y, text=label, anchor="w", fill=p["color"], font=font)
            bx = c.bbox(tid)
            rid = c.create_rectangle(bx[0] - 4, bx[1] - 2, bx[2] + 4, bx[3] + 2, fill="#14121f", outline=p["color"])
            c.tag_raise(tid, rid)
            pad = unit * 3
            boxes.append((min(x - pad, bx[0] - 4), min(y - pad, bx[1] - 2), max(x + pad, bx[2] + 4), max(y + pad, bx[3] + 2)))
        size = max(32, h // 12)
        for e in self.emotes:
            age = now - e["born"]
            x = e["x"] * w
            y = h * 0.9 - (h * 0.35) * (age / EMOTE_LIFE)  # float upwards
            c.create_image(x, y, image=self._emoji_image(e["emoji"], size))
            tid = c.create_text(x, y + size / 2 + 4, text=e["name"], anchor="n", fill=e["color"], font=font)
            bx = c.bbox(tid)
            boxes.append((min(x - size / 2, bx[0]), y - size / 2, max(x + size / 2, bx[2]), bx[3]))
        # Drawings: a line in the viewer's color, their name at the start.
        line_w = max(3, h // 160)
        for st in list(self.strokes.values()):
            pts = [(x * w, y * h) for x, y in st["points"]]
            if not pts:
                continue
            if len(pts) == 1:
                x, y = pts[0]
                c.create_oval(x - line_w, y - line_w, x + line_w, y + line_w, fill=st["color"], outline="")
            else:
                c.create_line(*[v for pt in pts for v in pt], fill=st["color"], width=line_w,
                              capstyle="round", joinstyle="round", smooth=True)
            x0, y0 = pts[0]
            tid = c.create_text(x0 + 6, y0 - 6, text=st["name"], anchor="sw", fill=st["color"], font=font)
            bx = c.bbox(tid)
            rid = c.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1, fill="#14121f", outline="")
            c.tag_raise(tid, rid)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            boxes.append((min(xs) - line_w, min(min(ys) - line_w, bx[1]), max(max(xs) + line_w, bx[2]),
                          max(ys) + line_w))

        # Chat: newest at the bottom, in the top-left corner (the status bubble is on the right).
        cfont = ("Segoe UI", -max(12, h // 40))
        y = MARGIN
        wrap = max(200, w // 2)
        prev_name, text_x = None, MARGIN + 8
        for m in chat:
            if m["name"] != prev_name:
                # First line of a run from this person: show their name.
                if prev_name is not None:
                    y += 4
                nid = c.create_text(MARGIN + 8, y + 4, text=m["name"] + ":", anchor="nw", fill=m["color"],
                                    font=cfont + ("bold",))
                nb = c.bbox(nid)
                text_x, bottom = nb[2] + 6, nb[3]
            else:
                bottom = y  # same person again: just the text, lined up under the previous one
            tid = c.create_text(text_x, y + 4, text=m["text"], anchor="nw", fill="#f1eefc", font=cfont,
                                width=max(120, wrap - (text_x - MARGIN)))
            tb = c.bbox(tid)
            bottom = max(bottom, tb[3]) + 4
            rid = c.create_rectangle(MARGIN, y, max(tb[2], text_x) + 8, bottom, fill="#14121f", outline="")
            c.tag_lower(rid)
            boxes.append((MARGIN, y, max(tb[2], text_x) + 8, bottom))
            y, prev_name = bottom, m["name"]
        self.boxes = [(l + int(x0), t + int(y0), l + int(x1), t + int(y1)) for x0, y0, x1, y1 in boxes]
        self.win.lift()


_fonts = {}
_emoji_cache = {}


def _font(size, bold=True):
    key = (size, bold)
    if key not in _fonts:
        try:
            _fonts[key] = ImageFont.truetype("segoeuib.ttf" if bold else "segoeui.ttf", size)
        except OSError:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def _emoji(emoji, size):
    key = (emoji, size)
    if key not in _emoji_cache:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, size - 1, size - 1), fill=(20, 18, 31, 230))
        try:
            draw.text((size / 2, size / 2), emoji, font=ImageFont.truetype("seguiemj.ttf", int(size * 0.62)),
                      anchor="mm", embedded_color=True)
        except OSError:
            pass
        _emoji_cache[key] = img
    return _emoji_cache[key]


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def stroke_expired(st, now):
    if st["done_at"] is not None:
        return now - st["done_at"] > STROKE_LIFE
    return now - st["at"] > STROKE_STALE


def draw_overlays(img, pings, emotes, status, strokes=()):
    """Draw what the overlay windows show onto a picture of the game (for the stream).

    Mirrors PingLayer and Overlay, so viewers see the same pings and bubble as the host.
    """
    now = time.monotonic()
    w, h = img.size
    img = img.convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    unit = max(10, h // 40)
    font = _font(max(12, h // 36))
    dark = (20, 18, 31, 235)
    for p in pings:
        age = now - p["born"]
        if age >= PING_LIFE:
            continue
        color = _hex(p["color"])
        x, y = p["x"] * w, p["y"] * h
        radius = unit * (0.6 + 1.4 * min(1.0, age / 0.35))
        d.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=3)
        pr = unit * (0.5 + 2.2 * ((age % 0.8) / 0.8))
        d.ellipse((x - pr, y - pr, x + pr, y + pr), outline=color, width=1)
        d.ellipse((x - unit * 0.3, y - unit * 0.3, x + unit * 0.3, y + unit * 0.3), fill=color, outline=dark, width=2)
        names = p["names"]
        label = names[-1] if p["count"] == 1 else f"×{p['count']}  {', '.join(names[-3:])}"
        tx, ty = x + radius + 6, y
        bx = d.textbbox((tx, ty), label, font=font, anchor="lm")
        d.rectangle((bx[0] - 4, bx[1] - 2, bx[2] + 4, bx[3] + 2), fill=dark, outline=color)
        d.text((tx, ty), label, font=font, fill=color, anchor="lm")
    line_w = max(3, h // 160)
    for st in strokes:
        if stroke_expired(st, now) or not st["points"]:
            continue
        color = _hex(st["color"])
        pts = [(x * w, y * h) for x, y in st["points"]]
        if len(pts) > 1:
            d.line(pts, fill=color, width=line_w, joint="curve")
        for x, y in (pts[0], pts[-1]):  # round ends
            d.ellipse((x - line_w / 2, y - line_w / 2, x + line_w / 2, y + line_w / 2), fill=color)
        x0, y0 = pts[0]
        bx = d.textbbox((x0 + 6, y0 - 6), st["name"], font=font, anchor="ls")
        d.rectangle((bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1), fill=dark)
        d.text((x0 + 6, y0 - 6), st["name"], font=font, fill=color, anchor="ls")
    size = max(32, h // 12)
    for e in emotes:
        age = now - e["born"]
        if age >= EMOTE_LIFE:
            continue
        x = int(e["x"] * w)
        y = int(h * 0.9 - (h * 0.35) * (age / EMOTE_LIFE))
        layer.alpha_composite(_emoji(e["emoji"], size), (x - size // 2, y - size // 2))
        d.text((x, y + size / 2 + 4), e["name"], font=font, fill=_hex(e["color"]), anchor="ma")
    if status:
        text, color = status
        bfont = _font(max(12, min(22, h // 34)))
        bx = d.textbbox((0, 0), text, font=bfont)
        bw, bh = bx[2] - bx[0] + 24, bx[3] - bx[1] + 12
        x0 = w - bw - MARGIN
        y0 = MARGIN
        d.rectangle((x0, y0, x0 + bw, y0 + bh), fill=dark, outline=(91, 79, 158), width=2)
        d.text((x0 + 12, y0 + 6 - bx[1]), text, font=bfont, fill=_hex(color))
    img.alpha_composite(layer)
    return img.convert("RGB")


class Overlay:
    def __init__(self, root, get_hwnd):
        self.get_hwnd = get_hwnd
        self.enabled = True
        self.state = None
        self.bbox = None  # on-screen rect while visible, so OCR can blank it out
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", KEY)
        self.win.configure(bg=KEY)
        self.box = tk.Frame(self.win, bg="#14121f", highlightthickness=2, highlightbackground="#5b4f9e")
        self.box.pack()
        self.label = tk.Label(self.box, bg="#14121f", fg=WAIT_COLOR, padx=12, pady=6)
        self.label.pack()
        self._styled = False
        self._font_px = None
        self._flash = None  # (text, color, until): a short note, e.g. "Paused"
        self.win.after(150, self._tick)

    def set_state(self, snapshot):
        self.state = snapshot

    def flash(self, text, color, seconds=2.0):
        """Show a short note in the bubble's place (works even with the bubble turned off)."""
        self._flash = (text, color, time.monotonic() + seconds)

    def _make_click_through(self):
        make_click_through(self.win)
        self._styled = True

    def current(self):
        """(text, color) the bubble shows right now, or None."""
        if self._flash and time.monotonic() < self._flash[2]:
            return self._flash[:2]
        return self._text() if self.enabled else None

    def _text(self):
        """One line that makes sense both to the host and to people watching the stream."""
        s = self.state
        if not s or not s.get("message"):
            return None
        players = s["players"]
        if not s.get("blocking"):
            # The host advances whenever they want; the bubble tells them who's still reading.
            players = [p for p in players if not p["host"]]
            if not players:
                return None
        done = sum(p["read"] for p in players)
        if s.get("advancing") or done == len(players):
            return "✓ Everyone read", DONE_COLOR
        waiting = [p["name"] for p in players if not p["read"]]
        return f"Waiting for {', '.join(waiting)}  ({done}/{len(players)})", WAIT_COLOR

    def _tick(self):
        try:
            self._update()
        finally:
            self.win.after(150, self._tick)

    def _hide(self):
        self.bbox = None
        self.win.withdraw()

    def _update(self):
        hwnd = self.get_hwnd()
        text = self.current()
        rect = winutil.client_rect_on_screen(hwnd) if hwnd else None
        if not text or not rect or not winutil.is_foreground(hwnd):
            self._hide()
            return
        l, t, r, b = rect
        font_px = max(12, min(22, (b - t) // 34))
        if font_px != self._font_px:
            self._font_px = font_px
            self.label.configure(font=("Segoe UI", -font_px, "bold"))
        self.label.configure(text=text[0], fg=text[1])

        self.win.deiconify()
        if not self._styled:
            self._make_click_through()
        self.win.update_idletasks()
        ow, oh = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = max(l, r - ow - MARGIN)  # top-right corner of the game
        y = t + MARGIN
        self.win.geometry(f"+{x}+{y}")
        self.win.lift()
        self.bbox = (x, y, x + ow, y + oh)
