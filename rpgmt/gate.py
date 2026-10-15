"""Holds back the host's "advance text" input while the lobby is still reading.

Works for every RPG Maker version because it acts at the OS input level: while
engaged, confirm/cancel keys and mouse clicks aimed at the game are swallowed.
The host's own confirm press counts as their Read vote. When everyone has read,
we inject a single Enter press into the game.
"""
import ctypes
import threading
import time
from ctypes import wintypes

from . import winutil
from .winutil import LRESULT, kernel32, user32

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x201, 0x202, 0x204, 0x205
WM_MOUSEWHEEL, WM_QUIT = 0x20A, 0x12
INPUT_KEYBOARD, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 1, 0x2, 0x8

VK_RETURN, VK_SPACE, VK_ESCAPE, VK_INSERT, VK_NUMPAD0 = 0x0D, 0x20, 0x1B, 0x2D, 0x60
VK_Z, VK_X, VK_C = 0x5A, 0x58, 0x43
CONFIRM_KEYS = {VK_RETURN, VK_SPACE, VK_Z, VK_C}            # count as the host's Read
BLOCKED_KEYS = CONFIRM_KEYS | {VK_ESCAPE, VK_X, VK_INSERT, VK_NUMPAD0}  # cancel also advances in MV/MZ

MAGIC = 0x52504D54  # "RPMT", tags input we inject ourselves so the hook lets it through
HOLD_SECONDS = 0.08  # old engines poll the keyboard once per frame; a tap must last a few frames

HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class InputGate:
    def __init__(self, on_host_read):
        self.on_host_read = on_host_read  # runs on the hook thread: must be fast
        self.hwnd = None
        self._engaged = False
        self._down = set()    # blocked keys currently held (swallowed presses)
        self._passed = set()  # keys whose press reached the game and are still held
        self._thread = None
        self._tid = None
        self._tap_lock = threading.Lock()
        self._tap_id = 0

    # --- hook thread -----------------------------------------------------
    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Install the keyboard/mouse hook (only needed for "hold the game")."""
        if self.running:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(2)

    def stop(self):
        self.engaged = False
        if self._tid and self.running:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._tid = None

    def _active(self):
        return self.engaged and self.hwnd and winutil.is_foreground(self.hwnd)

    def _kb_proc(self, n_code, w_param, l_param):
        if n_code == 0:
            k = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if not is_down:
                # Key releases always pass: swallowing one would leave the key
                # "stuck down" in the game, which then auto-advances every line.
                if k.dwExtraInfo != MAGIC:  # our own synthetic release doesn't mean the finger lifted
                    self._down.discard(k.vkCode)
                    self._passed.discard(k.vkCode)
            elif k.vkCode in BLOCKED_KEYS and k.dwExtraInfo != MAGIC and self._active():
                # Holding a key (auto-repeat) only votes once; a key that was already
                # held when the gate engaged needs a fresh press.
                if k.vkCode in CONFIRM_KEYS and k.vkCode not in self._down:
                    self.on_host_read()
                self._down.add(k.vkCode)
                return 1
            elif k.dwExtraInfo != MAGIC:
                self._passed.add(k.vkCode)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _mouse_proc(self, n_code, w_param, l_param):
        if n_code == 0 and w_param in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MOUSEWHEEL):
            m = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if (m.dwExtraInfo != MAGIC and self._active()
                    and winutil.point_in_window(self.hwnd, m.pt.x, m.pt.y)):
                if w_param == WM_LBUTTONDOWN:
                    self.on_host_read()
                return 1  # button releases are never swallowed (see keyboard above)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    @property
    def engaged(self):
        return self._engaged

    @engaged.setter
    def engaged(self, value):
        was, self._engaged = self._engaged, value
        if value and not was:
            # Keys the game saw go down and never saw released would keep
            # auto-repeating in the game; tell it they were released.
            for vk in list(self._passed & BLOCKED_KEYS):
                self._passed.discard(vk)
                self._down.add(vk)  # the physical key is still held: don't count it as a vote
                self._send(vk, True)

    def _run(self, ready):
        self._tid = kernel32.GetCurrentThreadId()
        # Keep references so the callbacks are not garbage-collected.
        self._kb_cb = HOOKPROC(self._kb_proc)
        self._mouse_cb = HOOKPROC(self._mouse_proc)
        hmod = kernel32.GetModuleHandleW(None)
        kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb, hmod, 0)
        ms = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb, hmod, 0)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(kb)
        user32.UnhookWindowsHookEx(ms)

    # --- injection -------------------------------------------------------
    def press_confirm(self, on_waiting=lambda: None, on_sent=lambda: None):
        """Send one Enter tap to the game (runs on a helper thread).

        on_waiting: the game isn't the active window, so the tap waits for it.
        on_sent: the tap was actually delivered."""
        with self._tap_lock:
            self._tap_id += 1
            tap_id = self._tap_id
        threading.Thread(target=self._tap, args=(VK_RETURN, tap_id, on_waiting, on_sent), daemon=True).start()

    @staticmethod
    def _send(vk, up):
        # Hardware scancodes: what games reading the keyboard directly (DirectInput,
        # raw input, SDL) see; Windows still turns them into normal key messages.
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(wVk=0, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=flags, time=0, dwExtraInfo=MAGIC)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _tap(self, vk, tap_id, on_waiting, on_sent):
        # SendInput goes to the active window, so never type into something else:
        # if the host is in another window, wait until the game is active again.
        deadline = time.monotonic() + 600
        if not winutil.is_foreground(self.hwnd):
            on_waiting()
        while not winutil.is_foreground(self.hwnd):
            if time.monotonic() > deadline or tap_id != self._tap_id:
                return  # gave up, or a newer tap replaced this one
            time.sleep(0.1)
        self._send(vk, False)
        time.sleep(HOLD_SECONDS)
        self._send(vk, True)
        on_sent()
