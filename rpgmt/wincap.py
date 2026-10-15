"""Captures one window's own picture (Windows Graphics Capture, like OBS/Discord).

Other windows on top of the game don't matter, and the game isn't asked to do
anything (unlike PrintWindow, which broke rendering in some games). Our own
overlay windows aren't in the picture either; the stream draws pings itself.
"""
import ctypes
import sys
import threading
import time
import types
from ctypes import wintypes

from PIL import Image

from . import winutil

DWMWA_EXTENDED_FRAME_BOUNDS = 9
STALE_AFTER = 1.5  # seconds without frames before we stop trusting the capture
dwmapi = ctypes.WinDLL("dwmapi")
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


def _stub_opencv():
    """windows_capture imports OpenCV (a 112 MB library) only for its "save frame to a
    file" helper, which RPGMT never uses. The app is built without OpenCV, so hand it
    a stand-in module."""
    if "cv2" in sys.modules:
        return
    try:
        import cv2  # noqa: F401 - present when running from source
    except ImportError:
        stub = types.ModuleType("cv2")
        stub.imwrite = lambda *args, **kwargs: False
        sys.modules["cv2"] = stub


def _client_offset(hwnd):
    """Where the client area starts inside the captured picture (which has the title bar)."""
    frame = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame)):
        return None
    client = winutil.client_rect_on_screen(hwnd)
    if client is None:
        return None
    return client[0] - frame.left, client[1] - frame.top, client[2] - client[0], client[3] - client[1]


class WindowCapture:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self._image = None
        self._at = 0.0
        self._lock = threading.Lock()
        self._control = None
        self.failed = None
        self.created = time.monotonic()
        self._offset = None
        self._offset_at = 0.0
        self._start()

    def _start(self):
        try:
            _stub_opencv()
            from windows_capture import WindowsCapture
        except ImportError as e:
            self.failed = e
            return
        try:
            cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=self.hwnd,
                                 minimum_update_interval=16)
        except Exception:  # noqa: BLE001 - borderless capture needs Windows 11
            try:
                cap = WindowsCapture(cursor_capture=False, window_hwnd=self.hwnd, minimum_update_interval=16)
            except Exception as e:  # noqa: BLE001
                self.failed = e
                return

        @cap.event
        def on_frame_arrived(frame, control):
            self._on_frame(frame)

        @cap.event
        def on_closed():
            self.failed = self.failed or RuntimeError("capture closed")

        try:
            self._control = cap.start_free_threaded()
        except Exception as e:  # noqa: BLE001
            self.failed = e

    def _on_frame(self, frame):
        now = time.monotonic()
        if self._offset is None or now - self._offset_at > 1.0:  # window may move or resize
            self._offset, self._offset_at = _client_offset(self.hwnd), now
        if self._offset is None:
            return
        x, y, w, h = self._offset
        if w <= 0 or h <= 0 or x + w > frame.width or y + h > frame.height:
            return
        client = frame.frame_buffer[y:y + h, x:x + w]
        img = Image.frombuffer("RGBA", (w, h), client.tobytes(), "raw", "BGRA", 0, 1).convert("RGB")
        with self._lock:
            self._image, self._at = img, now

    def latest(self):
        """The newest picture of the game's client area, or None."""
        with self._lock:
            if self._image is None or time.monotonic() - self._at > STALE_AFTER:
                # No new frames: WGC only sends frames when the picture changes, so a
                # still scene is fine; a minimized or closed window is not.
                if self._image is not None and winutil.is_window(self.hwnd) and \
                        winutil.client_rect_on_screen(self.hwnd) is not None:
                    return self._image
                return None
            return self._image

    def stop(self):
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:  # noqa: BLE001
                pass
            self._control = None


_captures = {}
_lock = threading.Lock()


def get(hwnd):
    """Shared capture for a window (started on first use), or None if unsupported."""
    with _lock:
        cap = _captures.get(hwnd)
        if cap is not None and cap.failed and time.monotonic() - cap.created < 5:
            return None  # don't hammer Windows with retries
        if cap is None or cap.failed:
            if cap is not None:
                cap.stop()
            for other in [h for h in _captures if not winutil.is_window(h)]:
                _captures.pop(other).stop()
            cap = _captures[hwnd] = WindowCapture(hwnd)
        return None if cap.failed else cap


def stop_all():
    with _lock:
        for cap in _captures.values():
            cap.stop()
        _captures.clear()
