"""Watches the game screen with OCR and reports when a dialogue line is showing.

Any readable text on the game screen counts as a line; the host presses F8 to
pause RPGMT while in menus. (An earlier "message box area" setting caused more
odd behaviour than it prevented.) A couple of noise filters stay: number-heavy
lines (HP, FPS counters) and lone single words (menu commands) are ignored.

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
CLEAR_TIME = 0.5         # no text this long = dialogue over (bridges gaps between boxes)
SAME_TEXT_REPEAT = 1.5   # after an advance, identical text this long = a new (repeated) line


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


def screen_text(lines):
    """The readable text on screen, or "" if there's none worth calling a line."""
    kept = [text for text, _, _ in lines if is_real_text(text)]
    # A real line has at least one sentence-like row; lone words ("Attack", "Item") don't count.
    if not any(len(text.split()) >= 2 for text in kept):
        return ""
    return normalize(" ".join(kept))


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
        self.min_chars = 4
        self.language = None
        self.paused = False
        self.clean = False
        self.get_masks = lambda: []  # screen rects of our own windows, blanked before OCR
        self.get_ping_boxes = lambda: []  # screen rects of viewers' pings/emotes
        self.last_reason = ""
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
        """Text currently on the game screen, or ""."""
        shot = capture_window(self.hwnd)
        if shot is None:
            return ""
        img, left, top = shot
        if left is not None:
            # Read from the screen (game-only capture unavailable): blank out our own
            # windows and viewers' pings so they aren't read as game text.
            draw = ImageDraw.Draw(img)
            for (l, t, r, b) in list(self.get_masks()) + list(self.get_ping_boxes()):
                draw.rectangle((l - left, t - top, r - left, b - top), fill="black")
        return self._verdict(screen_text(ocr.read_lines(img)))

    def _verdict(self, text):
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
