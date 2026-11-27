"""Windows WASAPI loopback capture for a process and its descendants."""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from contextlib import ExitStack
import logging
from pathlib import Path
import sys
import threading
from uuid import UUID


_HRESULT = ct.c_long
_PTR = ct.c_void_p
_P = ct.POINTER
_CALL = getattr(ct, "WINFUNCTYPE", ct.CFUNCTYPE)

_IID_AUDIO_CLIENT = UUID("1cb9ad4c-dbfa-4c32-b178-c2f568a703b2").bytes_le
_IID_CAPTURE_CLIENT = UUID("c8adbd64-e71e-48a0-a4de-185c395cd317").bytes_le
_CALLBACK_IIDS = {
    UUID(iid).bytes_le for iid in (
        "00000000-0000-0000-c000-000000000046",  # IUnknown
        "94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90",  # IAgileObject
        "41d949ab-9862-444a-80f6-c261334da5eb",  # IActivateAudioInterfaceCompletionHandler
    )
}
_PROCESS_LOOPBACK_DEVICE = r"VAD\Process_Loopback"
_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
_INCLUDE_TARGET_PROCESS_TREE = 0
_STREAMFLAGS_LOOPBACK = 0x00020000
_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
_BUFFERFLAGS_SILENT = 0x2
_VT_BLOB = 65
_log = logging.getLogger(__name__)


class _ActivationParams(ct.Structure):
    _fields_ = [
        ("activation_type", ct.c_int),
        ("target_pid", wt.DWORD),
        ("loopback_mode", ct.c_int),
    ]


class _Blob(ct.Structure):
    _fields_ = [("size", wt.ULONG), ("data", _PTR)]


class _BlobVariant(ct.Structure):
    # PROPVARIANT header followed by its BLOB member, with native pointer alignment.
    _fields_ = [("type", wt.WORD), ("reserved", wt.WORD * 3), ("blob", _Blob)]


class _WaveFormat(ct.Structure):
    _pack_ = 1
    _fields_ = [
        ("tag", wt.WORD), ("channels", wt.WORD), ("rate", wt.DWORD),
        ("bytes_per_second", wt.DWORD), ("block_align", wt.WORD),
        ("bits_per_sample", wt.WORD), ("extra_size", wt.WORD),
    ]


def _check(hr: int, operation: str) -> None:
    if hr < 0:
        raise OSError(f"{operation} failed (HRESULT 0x{hr & 0xffffffff:08X})")


def _method(interface, slot, result, *arg_types):
    vtable = ct.cast(interface, _P(_P(_PTR))).contents
    return _CALL(result, _PTR, *arg_types)(vtable[slot])


def _call(interface, slot, operation, arg_types=(), *args):
    _check(_method(interface, slot, _HRESULT, *arg_types)(interface, *args), operation)


def _release(interface):
    if interface:
        _method(interface, 2, wt.ULONG)(interface)


class _ActivationCallback:
    # Native references may outlive the capture thread when startup is cancelled.
    _live: dict[int, _ActivationCallback] = {}
    _lock = threading.Lock()

    def __init__(self, pid: int):
        self.done = threading.Event()
        self.params = _ActivationParams(
            _ACTIVATION_TYPE_PROCESS_LOOPBACK, pid, _INCLUDE_TARGET_PROCESS_TREE,
        )
        self.variant = _BlobVariant(
            _VT_BLOB, (wt.WORD * 3)(), _Blob(ct.sizeof(self.params), ct.addressof(self.params)),
        )
        self._refs = 1
        self._entries = (
            _CALL(_HRESULT, _PTR, _PTR, _P(_PTR))(self._query_interface),
            _CALL(wt.ULONG, _PTR)(self._add_ref),
            _CALL(wt.ULONG, _PTR)(self.release),
            _CALL(_HRESULT, _PTR, _PTR)(self._completed),
        )
        self._vtable = (_PTR * len(self._entries))(
            *(ct.cast(entry, _PTR) for entry in self._entries),
        )
        self._instance = ct.cast(self._vtable, _PTR)
        self.address = ct.addressof(self._instance)
        with self._lock:
            self._live[self.address] = self

    def _query_interface(self, this, iid, out):
        if ct.string_at(iid, 16) not in _CALLBACK_IIDS:
            out[0] = None
            return -2147467262  # E_NOINTERFACE
        out[0] = this
        self._add_ref(this)
        return 0

    def _add_ref(self, _this):
        with self._lock:
            self._refs += 1
            return self._refs

    def release(self, _this=None):
        with self._lock:
            self._refs -= 1
            if self._refs == 0:
                del self._live[self.address]
            return self._refs

    def _completed(self, _this, _operation):
        self.done.set()
        return 0


def _activate(pid: int, stopped: threading.Event) -> _PTR:
    activate = ct.WinDLL("Mmdevapi.dll").ActivateAudioInterfaceAsync
    activate.argtypes = (wt.LPCWSTR, _PTR, _P(_BlobVariant), _PTR, _P(_PTR))
    activate.restype = _HRESULT
    operation = _PTR()
    callback = _ActivationCallback(pid)
    try:
        _check(activate(
            _PROCESS_LOOPBACK_DEVICE, _IID_AUDIO_CLIENT, ct.byref(callback.variant),
            callback.address, ct.byref(operation),
        ), "ActivateAudioInterfaceAsync")
        while not callback.done.wait(0.02):
            if stopped.is_set():
                raise RuntimeError("process audio activation cancelled")
        hr = _HRESULT()
        client = _PTR()
        _call(operation, 3, "GetActivateResult", (_P(_HRESULT), _P(_PTR)),
              ct.byref(hr), ct.byref(client))
        _check(hr.value, "process loopback activation")
        return client
    finally:
        _release(operation)
        callback.release()


def window_process_id(hwnd: int) -> int:
    get_pid = ct.WinDLL("User32.dll", use_last_error=True).GetWindowThreadProcessId
    get_pid.argtypes = (wt.HWND, _P(wt.DWORD))
    get_pid.restype = wt.DWORD
    pid = wt.DWORD()
    if not get_pid(hwnd, ct.byref(pid)) or not pid.value:
        raise OSError(f"GetWindowThreadProcessId failed for HWND {hwnd}")
    return pid.value


def process_loopback_supported() -> bool:
    # Try activation on 19041+. The OS decides whether this interface is available.
    return sys.platform == "win32" and sys.getwindowsversion().build >= 19041


def _packets(capture, block_align: int, stopped: threading.Event):
    next_frames = wt.UINT()
    data = _PTR()
    frames = wt.UINT()
    flags = wt.DWORD()
    while not stopped.is_set():
        _call(capture, 5, "GetNextPacketSize", (_P(wt.UINT),), ct.byref(next_frames))
        if not next_frames.value:
            stopped.wait(0.01)
            continue
        _call(capture, 3, "GetBuffer",
              (_P(_PTR), _P(wt.UINT), _P(wt.DWORD), _PTR, _PTR),
              ct.byref(data), ct.byref(frames), ct.byref(flags), None, None)
        try:
            size = frames.value * block_align
            packet = bytes(size) if flags.value & _BUFFERFLAGS_SILENT else ct.string_at(data, size)
        finally:
            _call(capture, 4, "ReleaseBuffer", (wt.UINT,), frames.value)
        yield packet


class ProcessAudioCaptureThread(threading.Thread):
    def __init__(self, output_path: Path, pid: int):
        super().__init__(daemon=True, name="ProcessAudioCapture")
        self.output_path = Path(output_path)
        self.pid = pid
        self.ready = threading.Event()
        self.sample_rate = 0
        self.channels = 0
        self.error: str | None = None
        self.bytes_written = 0
        self._stopped = threading.Event()
        self._startup_lock = threading.Lock()

    def stop(self) -> None:
        self._stopped.set()

    def cancel_pending_start(self) -> bool:
        """Cancel a timed-out startup unless the thread already published its result."""
        with self._startup_lock:
            if self.ready.is_set():
                return False
            self.stop()
            return True

    def run(self) -> None:
        try:
            if not process_loopback_supported():
                raise OSError("Windows process loopback is unavailable")

            ole = ct.WinDLL("ole32.dll")
            ole.CoInitializeEx.argtypes = (_PTR, wt.DWORD)
            ole.CoInitializeEx.restype = _HRESULT
            ole.CoUninitialize.argtypes = ()
            ole.CoUninitialize.restype = None
            with ExitStack() as cleanup:
                _check(ole.CoInitializeEx(None, 0), "CoInitializeEx")  # COINIT_MULTITHREADED
                cleanup.callback(ole.CoUninitialize)
                client = _activate(self.pid, self._stopped)
                cleanup.callback(_release, client)

                rate, channels, bits = 48000, 2, 16
                block_align = channels * bits // 8
                fmt = _WaveFormat(1, channels, rate, rate * block_align, block_align, bits, 0)
                # IAudioClient::Initialize, shared mode with an explicit PCM format.
                _call(client, 3, "IAudioClient.Initialize",
                      (ct.c_int, wt.DWORD, ct.c_int64, ct.c_int64, _P(_WaveFormat), _PTR),
                      0, _STREAMFLAGS_LOOPBACK | _STREAMFLAGS_AUTOCONVERTPCM, 0, 0,
                      ct.byref(fmt), None)
                capture = _PTR()
                _call(client, 14, "IAudioClient.GetService", (_PTR, _P(_PTR)),
                      _IID_CAPTURE_CLIENT, ct.byref(capture))
                cleanup.callback(_release, capture)
                _call(client, 10, "IAudioClient.Start")
                cleanup.callback(_call, client, 11, "IAudioClient.Stop")

                with self._startup_lock:
                    if self._stopped.is_set():
                        raise RuntimeError("process audio stopped before startup completed")
                    output = cleanup.enter_context(self.output_path.open("wb"))
                    self.sample_rate, self.channels = rate, channels
                    _log.info("audio capture started: process pid=%d sr=%d ch=%d",
                              self.pid, rate, channels)
                    self.ready.set()
                for packet in _packets(capture, block_align, self._stopped):
                    self.bytes_written += output.write(packet)
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__
            _log.warning("process audio capture failed: pid=%d: %s", self.pid, self.error)
        finally:
            self.ready.set()
