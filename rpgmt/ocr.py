"""Screen capture + Windows built-in OCR (Windows.Media.Ocr). No external install."""
import asyncio

from PIL import Image, ImageChops, ImageGrab, ImageOps
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

from . import wincap, winutil


def available_languages():
    return [l.language_tag for l in OcrEngine.available_recognizer_languages]


def capture_window(hwnd):
    """Picture of the game's client area: (image, screen_left, screen_top) or None.

    Normally the window's own picture (Windows Graphics Capture): other windows on
    top don't matter and screen_left/top are None. If that isn't available, the
    screen is read instead; then covering windows (and our overlays) are in it.
    """
    cap = wincap.get(hwnd)
    img = cap.latest() if cap else None
    if img is not None:
        return img, None, None
    rect = winutil.client_rect_on_screen(hwnd)
    if rect is None:
        return None
    return ImageGrab.grab(bbox=rect, all_screens=True), rect[0], rect[1]


def crop_fraction(img, region):
    """Crop by (left, top, right, bottom) fractions; None if the area is too small."""
    w, h = img.size
    box = (int(w * region[0]), int(h * region[1]), int(w * region[2]), int(h * region[3]))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return img.crop(box)


def capture_region(hwnd, region):
    """Grab part of the game's client area (region = fractions 0..1)."""
    shot = capture_window(hwnd)
    return crop_fraction(shot[0], region) if shot else None


def isolate_bright_text(img: Image.Image) -> Image.Image:
    """Keep only near-white pixels (RPG Maker's default text color) as black on white.

    Removes busy backgrounds showing through translucent message windows and
    the dark outline around the letters.
    """
    r, g, b = img.convert("RGB").split()
    low = ImageChops.darker(ImageChops.darker(r, g), b)
    high = ImageChops.lighter(ImageChops.lighter(r, g), b)
    bright = low.point(lambda p: 255 if p >= 200 else 0)
    gray = ImageChops.subtract(high, low).point(lambda p: 255 if p < 60 else 0)
    text = ImageChops.multiply(bright, gray)
    out = ImageOps.expand(ImageOps.invert(text), 16, 255)
    return out.resize((out.width * 2, out.height * 2), Image.LANCZOS).convert("RGB")


class Ocr:
    def __init__(self, language_tag=None, clean=False):
        self.clean = clean
        if language_tag:
            self.engine = OcrEngine.try_create_from_language(Language(language_tag))
        else:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError("Windows OCR is not available for this language")
        self.loop = asyncio.new_event_loop()

    def _prepare(self, img, clean):
        """Returns (processed image, scale, pad) where original_y = y / scale - pad."""
        scale, pad = 1.0, 0
        if clean:
            img, scale, pad = isolate_bright_text(img), 2.0, 16
        # Windows OCR handles RPG Maker fonts best at native size; upscaling only
        # helps when the window is tiny (e.g. a 2000/2003 game at 1x zoom).
        if img.height < 80:
            img = img.resize((img.width * 2, img.height * 2), Image.BICUBIC)
            scale *= 2
        max_dim = OcrEngine.max_image_dimension
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            scale *= ratio
        return img, scale, pad

    def read(self, img: Image.Image) -> str:
        return "\n".join(text for text, _, _ in self.read_lines(img))

    def read_lines(self, img: Image.Image):
        """OCR with positions: [(text, top, bottom)] with top/bottom as 0..1 of img height."""
        if self.clean:
            lines = self._read_lines(img, clean=True)
            # The cleanup helps outlined text on busy backgrounds but can erase thin
            # fonts entirely; then the plain picture is the better read.
            if any(len(text.split()) >= 2 for text, _, _ in lines):
                return lines
        return self._read_lines(img, clean=False)

    def _read_lines(self, img, clean):
        height = img.height
        img, scale, pad = self._prepare(img, clean)
        lines = []
        for line in self.recognize(img):
            rects = [w.bounding_rect for w in line.words]
            if not rects:
                continue
            top = min(r.y for r in rects) / scale - pad
            bottom = max(r.y + r.height for r in rects) / scale - pad
            lines.append((line.text, top / height, bottom / height))
        return lines

    def recognize(self, img: Image.Image):
        writer = DataWriter()
        writer.write_bytes(img.convert("RGBA").tobytes("raw", "BGRA"))
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, img.width, img.height
        )
        return self.loop.run_until_complete(self.engine.recognize_async(bitmap)).lines
