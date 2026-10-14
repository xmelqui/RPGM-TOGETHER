"""Thin ctypes wrappers around the Win32 calls we need (windows, DPI, input)."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND

GA_ROOT = 2


def set_dpi_aware():
    """Make screen coordinates physical pixels so capture rects line up."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def list_windows():
    """Visible top-level windows with a title: [(hwnd, title)]."""
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = window_title(hwnd)
            if title.strip():
                out.append((hwnd, title))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def is_window(hwnd):
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def client_rect_on_screen(hwnd):
    """(left, top, right, bottom) of the client area in screen pixels, or None."""
    if not is_window(hwnd) or user32.IsIconic(hwnd):
        return None
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        return None
    return (pt.x, pt.y, pt.x + w, pt.y + h)


user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def window_rect(hwnd):
    """Whole window (frame included) in screen pixels."""
    rc = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


def process_id(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def root_of(hwnd):
    return user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None


def is_foreground(hwnd):
    fg = user32.GetForegroundWindow()
    return bool(fg) and root_of(fg) == root_of(hwnd)


def point_in_window(hwnd, x, y):
    under = user32.WindowFromPoint(wintypes.POINT(x, y))
    return bool(under) and root_of(under) == root_of(hwnd)
