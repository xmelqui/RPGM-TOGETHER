"""`RPGMT.exe --selftest`: checks every part works on this PC and writes a report.

Useful when a friend says "it doesn't work": the report says which part failed.
"""
import fractions
import os
import platform
import sys
import time
import traceback

from .tunnel import APP_DIR

REPORT = APP_DIR / "selftest.txt"


def _check(name, fn, lines):
    start = time.perf_counter()
    try:
        detail = fn() or ""
        lines.append(f"[ OK ] {name} ({(time.perf_counter() - start) * 1000:.0f} ms) {detail}")
        return True
    except Exception:  # noqa: BLE001
        lines.append(f"[FAIL] {name}\n{traceback.format_exc()}")
        return False


def _ocr():
    from PIL import Image, ImageDraw, ImageFont

    from .ocr import Ocr
    img = Image.new("RGB", (600, 80), (20, 20, 60))
    ImageDraw.Draw(img).text((10, 20), "Welcome to the village!", fill="white",
                             font=ImageFont.truetype("arial.ttf", 28))
    text = Ocr().read(img)
    if "village" not in text.lower():
        raise RuntimeError(f"OCR read {text!r}")
    return repr(text)


def _video():
    import av
    from aiortc.codecs import get_encoder
    from aiortc.rtcrtpparameters import RTCRtpCodecParameters
    from PIL import Image
    out = []
    for mime in ("video/VP8", "video/H264"):
        enc = get_encoder(RTCRtpCodecParameters(mimeType=mime, clockRate=90000))
        frame = av.VideoFrame.from_image(Image.new("RGB", (816, 624), (40, 60, 90)))
        frame.pts, frame.time_base = 0, fractions.Fraction(1, 90000)
        packets, _ = enc.encode(frame)
        out.append(f"{mime.split('/')[1]}={sum(len(p) for p in packets)}B")
    return " ".join(out)


def _audio_encode():
    import av
    from aiortc.codecs import get_encoder
    from aiortc.rtcrtpparameters import RTCRtpCodecParameters
    enc = get_encoder(RTCRtpCodecParameters(mimeType="audio/opus", clockRate=48000, channels=2))
    frame = av.AudioFrame(format="s16", layout="stereo", samples=960)
    frame.planes[0].update(b"\x00" * 960 * 4)
    frame.sample_rate, frame.pts, frame.time_base = 48000, 0, fractions.Fraction(1, 48000)
    packets, _ = enc.encode(frame)
    return f"opus={sum(len(p) for p in packets)}B"


def _audio_capture():
    from .audio import GameAudio
    errors = []
    cap = GameAudio(os.getpid(), on_error=errors.append)
    cap.started.wait(5)
    cap.stop(wait=True)
    if errors:
        raise errors[0]
    return "per-game sound capture available"


def _window_capture():
    import tkinter as tk

    from . import wincap, winutil
    root = tk.Tk()
    root.geometry("320x200+40+40")
    root.configure(bg="#3060c0")
    root.update()
    hwnd = winutil.root_of(root.winfo_id())
    try:
        cap = wincap.get(hwnd)
        if cap is None:
            raise RuntimeError("Windows Graphics Capture is not available")
        img = None
        for _ in range(100):
            root.update()
            img = cap.latest()
            if img is not None:
                break
            time.sleep(0.02)
        if img is None:
            raise RuntimeError("no frames arrived")
        if img.getpixel((img.width // 2, img.height // 2))[2] < 150:
            raise RuntimeError(f"unexpected picture {img.getpixel((img.width // 2, img.height // 2))}")
        return f"game window capture works ({img.width}x{img.height})"
    finally:
        wincap.stop_all()
        root.destroy()


def _webview():
    import webview  # noqa: F401
    from webview.platforms import winforms  # noqa: F401 - needs .NET + WebView2 loader
    return "viewer window component loads"


def _network():
    from .netinfo import join_addresses
    return ", ".join(f"{ip} ({name})" for name, ip in join_addresses()) or "no network adapter"


def run():
    from . import __version__
    lines = [f"RPGMT {__version__} self-test  {time.strftime('%Y-%m-%d %H:%M')}",
             f"Windows {platform.version()}  Python {platform.python_version()}  frozen={getattr(sys, 'frozen', False)}",
             ""]
    checks = [("Text reading (Windows OCR)", _ocr), ("Video encoding", _video),
              ("Audio encoding", _audio_encode), ("Game sound capture", _audio_capture),
              ("Game window capture", _window_capture),
              ("Viewer window", _webview), ("Network addresses", _network)]
    ok = all([_check(name, fn, lines) for name, fn in checks])
    lines += ["", "ALL GOOD" if ok else "SOME CHECKS FAILED"]
    APP_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), "utf-8")
    return ok
