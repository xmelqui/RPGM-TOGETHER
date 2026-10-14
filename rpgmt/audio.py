"""Captures only the game's sound (not Discord, not music players).

Uses Windows' per-process loopback capture (Windows 10 2004+): the audio a
process tree plays, as 48 kHz stereo 16-bit PCM.
"""
import ctypes
import threading
import time
from ctypes import POINTER, byref, c_uint32, c_ulonglong, c_void_p, wintypes

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, COMObject

SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * 2  # 16-bit

VAD_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
LOOPBACK_MODE_INCLUDE_TREE = 0
VT_BLOB = 0x41


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", ctypes.c_int)]


class ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("ProcessLoopbackParams", PROCESS_LOOPBACK_PARAMS)]


class BLOB(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", c_void_p)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT), ("r2", wintypes.USHORT),
                ("r3", wintypes.USHORT), ("blob", BLOB)]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(c_void_p), "data"),
                  (["out"], POINTER(c_uint32), "frames"), (["out"], POINTER(wintypes.DWORD), "flags"),
                  (["out"], POINTER(c_ulonglong), "position"), (["out"], POINTER(c_ulonglong), "qpc")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "frames")),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize", (["in"], ctypes.c_int, "mode"), (["in"], wintypes.DWORD, "flags"),
                  (["in"], ctypes.c_longlong, "duration"), (["in"], ctypes.c_longlong, "period"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], c_void_p, "session")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "frames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(ctypes.c_longlong), "latency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "frames")),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], ctypes.c_int, "mode"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["out"], POINTER(c_void_p), "closest")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(c_void_p), "format")),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(ctypes.c_longlong), "default"),
                  (["out"], POINTER(ctypes.c_longlong), "minimum")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE, "event")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(c_void_p), "service")),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult", (["out"], POINTER(HRESULT), "result"),
                  (["out"], POINTER(POINTER(IUnknown)), "iface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "operation")),
    ]


class IAgileObject(IUnknown):
    _iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
    _methods_ = []


class _Completion(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self):
        super().__init__()
        self.done = threading.Event()

    def ActivateCompleted(self, this, operation):  # noqa: N802 - COM name
        self.done.set()
        return 0


mmdevapi = ctypes.WinDLL("Mmdevapi")
mmdevapi.ActivateAudioInterfaceAsync.argtypes = [wintypes.LPCWSTR, POINTER(GUID), POINTER(PROPVARIANT),
                                                 c_void_p, POINTER(c_void_p)]
mmdevapi.ActivateAudioInterfaceAsync.restype = HRESULT


def _open_process_loopback(pid):
    params = ACTIVATION_PARAMS(ACTIVATION_TYPE_PROCESS_LOOPBACK,
                               PROCESS_LOOPBACK_PARAMS(pid, LOOPBACK_MODE_INCLUDE_TREE))
    prop = PROPVARIANT(vt=VT_BLOB, blob=BLOB(ctypes.sizeof(params), ctypes.cast(byref(params), c_void_p)))
    handler = _Completion()
    handler_ptr = handler.QueryInterface(IActivateAudioInterfaceCompletionHandler)
    op_raw = c_void_p()
    iid = IAudioClient._iid_
    mmdevapi.ActivateAudioInterfaceAsync(VAD_PROCESS_LOOPBACK, byref(iid), byref(prop),
                                         ctypes.cast(handler_ptr, c_void_p), byref(op_raw))
    if not handler.done.wait(5):
        raise RuntimeError("Windows didn't answer the audio capture request")
    op = ctypes.cast(op_raw, POINTER(IActivateAudioInterfaceAsyncOperation))
    hr, iface = op.GetActivateResult()
    if hr != 0 or not iface:
        raise OSError(f"Process audio capture unavailable (HRESULT {hr & 0xFFFFFFFF:#010x})")
    client = iface.QueryInterface(IAudioClient)
    fmt = WAVEFORMATEX(1, CHANNELS, SAMPLE_RATE, SAMPLE_RATE * BYTES_PER_FRAME, BYTES_PER_FRAME, 16, 0)
    client.Initialize(AUDCLNT_SHAREMODE_SHARED,
                      AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                      | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
                      2_000_000, 0, byref(fmt), None)  # 200 ms buffer
    service = client.GetService(byref(IAudioCaptureClient._iid_))
    capture = ctypes.cast(service, POINTER(IAudioCaptureClient))
    return client, capture, (handler, op)  # keep the COM helpers alive


class GameAudio:
    """Background capture of one process's sound into a byte queue for the stream."""

    def __init__(self, pid, on_error=lambda e: None):
        self.pid = pid
        self.on_error = on_error
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.started = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, wait=False):
        self._stop.set()
        if wait and self._thread is not threading.current_thread():
            self._thread.join(2)  # leave Windows' audio APIs cleanly before the app exits

    def read(self, nbytes):
        """Up to nbytes of PCM; pads with silence when the game is quiet."""
        with self._lock:
            # Don't let latency build up if the stream falls behind.
            if len(self._buf) > SAMPLE_RATE * BYTES_PER_FRAME // 4:
                del self._buf[: len(self._buf) - nbytes * 2]
            out = bytes(self._buf[:nbytes])
            del self._buf[:nbytes]
        return out + b"\x00" * (nbytes - len(out))

    def _run(self):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            client, capture, _keep = _open_process_loopback(self.pid)
            client.Start()
            self.started.set()
            while not self._stop.is_set():
                time.sleep(0.01)
                while capture.GetNextPacketSize() > 0:
                    data, frames, flags, _, _ = capture.GetBuffer()
                    n = frames * BYTES_PER_FRAME
                    chunk = b"\x00" * n if flags & AUDCLNT_BUFFERFLAGS_SILENT else ctypes.string_at(data, n)
                    capture.ReleaseBuffer(frames)
                    with self._lock:
                        self._buf += chunk
            client.Stop()
        except Exception as e:  # noqa: BLE001
            self.on_error(e)
        finally:
            self.started.set()
            comtypes.CoUninitialize()
