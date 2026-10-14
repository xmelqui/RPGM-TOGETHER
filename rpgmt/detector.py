"""Watches the game screen with OCR and reports when a dialogue line is showing.

The whole game screen is read at once so menus can be told apart from dialogue:
dialogue is text inside the message box area with (almost) nothing elsewhere,
while item/equip/save menus put text all over the screen.

A line is reported once its text is stable (the typewriter effect has
finished). Small OCR jitter between frames is tolerated via fuzzy matching.
"""
import difflib
import re
import threading
import time

from PIL import ImageDraw

from .ocr import Ocr, capture_window

INTERVAL = 0.1           # seconds between OCR samples (one sample takes ~30-50 ms)
STABLE_TIME = 0.35       # text unchanged this long = typewriter finished, announce the line
CLEAR_TIME = 0.5         # message box empty this long = dialogue over (bridges gaps between boxes)
SAME_TEXT_REPEAT = 1.5   # after an advance, identical text this long = a new (repeated) line
NAME_BAND = 0.12         # text this close above the message box is the speaker's name box
MENU_LINES = 3           # this many text lines outside the message box = a menu, not dialogue


def normalize(text):
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r" ([.,!?;:])", r"\1", text)  # OCR often detaches punctuation


def same_frame(a, b):
    """Strict check used to decide the text stopped changing (typewriter done).

    Allows a 1-2 character wobble (e.g. the blinking "continue" arrow) but not
    growth, so a half-typed line is never reported as finished.
    """
    if a == b:
        return True
    return abs(len(a) - len(b)) <= 2 and similar(a, b, 0.95)


def is_real_text(line):
    """Ignore OCR specks and number-heavy lines (HP/MP, gold, item counts)."""
    alnum = [c for c in line if c.isalnum()]
    if len(alnum) < 3:
        return False
    digits = sum(c.isdigit() for c in alnum)
    return digits / len(alnum) < 0.3


def classify(lines, region):
    """Split OCR lines into (message box text, number of text lines elsewhere)."""
    top, bottom = region[1], region[3]
    inside, outside = [], 0
    for text, line_top, line_bottom in lines:
        if not is_real_text(text):
            continue
        center = (line_top + line_bottom) / 2
        if top <= center <= bottom:
            inside.append(text)
        elif center < top - NAME_BAND or center > bottom:
            outside += 1
    # Dialogue has sentences; command lists ("Fight / Escape", "Attack / Skill") are
    # one word per line.
    if not any(len(text.split()) >= 2 for text in inside):
        return "", outside
    return normalize(" ".join(inside)), outside


def similar(a, b, threshold=0.85):
    if a == b:
        return True
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


class Detector:
    def __init__(self, on_message, on_clear, on_error=None, on_dialogue=lambda: None):
        self.on_dialogue = on_dialogue  # dialogue appeared (may still be typing): start holding keys now
        self.on_message = on_message    # line finished typing: announce it to the lobby
        self.on_clear = on_clear        # no more dialogue: stop holding keys
        self.on_error = on_error or (lambda e: None)
        self.hwnd = None
        self.region = (0.0, 0.65, 1.0, 1.0)
        self.min_chars = 4
        self.language = None
        self.paused = False
        self.clean = False
        self.get_masks = lambda: []  # screen rects of our own windows, blanked before OCR
        self.get_ping_boxes = lambda: []  # screen rects of viewers' pings/emotes
        self.last_reason = ""
        self.occluded = False
        self._stop = threading.Event()
        self._thread = None
        self._current = None
        self._active = False  # dialogue on screen (on_dialogue sent, on_clear not yet)
        self._advanced_at = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def mark_advanced(self):
        """Called right after we sent the confirm key to the game."""
        self._advanced_at = time.monotonic()

    def _meaningful(self, text):
        return sum(c.isalnum() for c in text) >= self.min_chars

    def _sample(self, ocr):
        """Dialogue text currently on screen, or "" (nothing, or a menu).

        Sets self.occluded when a viewer's ping covers the message box: the text
        may then be partly hidden, so it's only good for "is there dialogue"."""
        shot = capture_window(self.hwnd)
        if shot is None:
            return ""
        img, left, top = shot
        if left is None:
            # The game window's own picture: our overlays and other windows aren't in it.
            self.occluded = False
            text, outside = classify(ocr.read_lines(img), self.region)
            return self._verdict(text, outside)
        pings = self.get_ping_boxes()
        w, h = img.size
        box = (left + w * self.region[0], top + h * self.region[1],
               left + w * self.region[2], top + h * self.region[3])
        self.occluded = any(l < box[2] and r > box[0] and t < box[3] and b > box[1] for l, t, r, b in pings)
        draw = ImageDraw.Draw(img)
        for (l, t, r, b) in list(self.get_masks()) + list(pings):
            draw.rectangle((l - left, t - top, r - left, b - top), fill="black")
        text, outside = classify(ocr.read_lines(img), self.region)
        return self._verdict(text, outside)

    def _verdict(self, text, outside):
        if outside >= MENU_LINES:
            self.last_reason = f"menu ({outside} text lines outside the message box)"
            return ""
        if not self._meaningful(text):
            self.last_reason = "no dialogue"
            return ""
        self.last_reason = "dialogue"
        return text

    def _run(self):
        try:
            ocr = Ocr(self.language, self.clean)
        except Exception as e:  # noqa: BLE001
            self.on_error(e)
            return
        last_text, last_change, empty_since = None, 0.0, None
        while not self._stop.is_set():
            time.sleep(INTERVAL)
            ocr.clean = self.clean
            if self.paused or not self.hwnd:
                self._end_dialogue()
                last_text, empty_since = None, None
                continue
            try:
                text = self._sample(ocr)
            except Exception as e:  # noqa: BLE001
                self.on_error(e)
                continue
            now = time.monotonic()
            if self.occluded:
                # A ping hides part of the box: still start holding keys if dialogue shows
                # up, but don't announce or end lines on a partly hidden frame.
                if text and not self._active:
                    self._active = True
                    self.on_dialogue()
                continue
            if last_text is None or not same_frame(text, last_text):
                last_text, last_change = text, now

            if not text:
                empty_since = empty_since or now
                if now - empty_since >= CLEAR_TIME:
                    self._end_dialogue()
                continue
            empty_since = None
            if not self._active:
                # Hold the host's keys right away, even while the line is still typing,
                # so a quick Enter can't skip it before anyone sees it.
                self._active = True
                self.on_dialogue()
            if now - last_change < STABLE_TIME:
                continue  # still typing

            repeated = (
                self._advanced_at is not None
                and now - self._advanced_at > SAME_TEXT_REPEAT
            )
            if self._current is None or not similar(text, self._current) or repeated:
                self._current = text
                self._advanced_at = None
                self.on_message(text)

    def _end_dialogue(self):
        if self._active or self._current is not None:
            self._active = False
            self._current = None
            self._advanced_at = None
            self.on_clear()
