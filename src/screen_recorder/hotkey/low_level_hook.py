"""WH_KEYBOARD_LL low-level keyboard hook — OS 가 가로채는 시스템 단축키
(Win+Shift+S 등) 를 KStudio 가 먼저 잡기 위한 모듈.

안전 패턴 (반드시 지킬 것):
  1. 콜백 자체는 즉시 리턴 — 무거운 작업 금물 (모든 키가 이 콜백을 거침).
  2. Python 콜백에서 예외가 raise 되면 OS 가 자동으로 hook 을 떼버려 다음 키부터
     동작 안 함 — `try / except` 로 모든 예외를 흡수.
  3. 콜백 인스턴스(`WINFUNCTYPE` 객체) 는 hook 살아있는 동안 가비지 컬렉션되면
     안 됨 — 클래스 멤버로 보관.
  4. 종료 시 반드시 `UnhookWindowsHookEx` — atexit 으로 안전망.
  5. 일치 키 차단 시 `CallNextHookEx` 호출 안 함 (= 1 리턴) → OS Snipping Tool
     같은 후속 처리기에 키가 도달 안 함.
  6. 매칭되는 키만 우리 시그널 emit + 차단; 그 외 키는 즉시 통과.

호출 흐름:
    hook = LowLevelKeyboardHook()
    hook.set_targets([(MOD_WIN | MOD_SHIFT, ord("S"))])
    hook.activated.connect(handler)
    hook.install()
    ...
    hook.uninstall()    # 또는 atexit
"""
from __future__ import annotations
import atexit
import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QObject, Signal


_log = logging.getLogger(__name__)
_IS_WIN = sys.platform == "win32"

# ---------- Win32 상수 ----------
_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105

_VK_LWIN = 0x5B
_VK_RWIN = 0x5C
_VK_LSHIFT = 0xA0
_VK_RSHIFT = 0xA1
_VK_LCONTROL = 0xA2
_VK_RCONTROL = 0xA3
_VK_LMENU = 0xA4   # Alt
_VK_RMENU = 0xA5

# RegisterHotKey 와 동일한 modifier 비트 정의 (parser.py 와 호환).
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


# KBDLLHOOKSTRUCT 정의
class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


# 콜백 시그니처: LRESULT CALLBACK LowLevelKeyboardProc(int, WPARAM, LPARAM)
_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,         # LRESULT
    ctypes.c_int,          # nCode
    wintypes.WPARAM,
    wintypes.LPARAM,
) if _IS_WIN else None


def _current_modifier_state() -> int:
    """현재 눌린 modifier 비트마스크. RegisterHotKey 형식과 호환."""
    if not _IS_WIN:
        return 0
    user32 = ctypes.windll.user32
    state = 0
    # GetAsyncKeyState 의 high bit (0x8000) 가 "현재 눌림" 의미.
    if user32.GetAsyncKeyState(_VK_LWIN) & 0x8000 or user32.GetAsyncKeyState(_VK_RWIN) & 0x8000:
        state |= MOD_WIN
    if user32.GetAsyncKeyState(_VK_LSHIFT) & 0x8000 or user32.GetAsyncKeyState(_VK_RSHIFT) & 0x8000:
        state |= MOD_SHIFT
    if user32.GetAsyncKeyState(_VK_LCONTROL) & 0x8000 or user32.GetAsyncKeyState(_VK_RCONTROL) & 0x8000:
        state |= MOD_CONTROL
    if user32.GetAsyncKeyState(_VK_LMENU) & 0x8000 or user32.GetAsyncKeyState(_VK_RMENU) & 0x8000:
        state |= MOD_ALT
    return state


_MODIFIER_VKS = {
    _VK_LWIN, _VK_RWIN, _VK_LSHIFT, _VK_RSHIFT,
    _VK_LCONTROL, _VK_RCONTROL, _VK_LMENU, _VK_RMENU,
}


class LowLevelKeyboardHook(QObject):
    """WH_KEYBOARD_LL 래퍼 — 등록된 (modifiers, vk) 조합과 일치하는 키만 가로챔.

    매칭 시 `activated` 시그널 emit + OS 후속 처리 차단.
    매칭 안 되면 즉시 통과 (CallNextHookEx).
    """

    activated = Signal(int, int)   # (modifiers, vk)

    def __init__(self) -> None:
        super().__init__()
        self._hhook: Optional[int] = None
        self._targets: set[tuple[int, int]] = set()
        # 콜백 인스턴스를 멤버로 보관해 GC 방지 (반드시).
        self._proc = None
        self._user32 = ctypes.windll.user32 if _IS_WIN else None
        self._kernel32 = ctypes.windll.kernel32 if _IS_WIN else None
        self._installed = False
        if _IS_WIN:
            atexit.register(self._safe_uninstall)

    # ---------- 외부 API ----------
    def set_targets(self, targets: Iterable[tuple[int, int]]) -> None:
        """가로챌 (modifiers, vk) 목록 설정. 비어 있으면 모든 키가 통과."""
        self._targets = {(int(m), int(vk)) for m, vk in targets}

    def install(self) -> bool:
        """hook 등록. 이미 등록돼 있으면 no-op. 성공 시 True."""
        if not _IS_WIN:
            return False
        if self._installed:
            return True
        try:
            # WINFUNCTYPE 객체는 살아 있어야 함.
            self._proc = _HOOKPROC(self._raw_callback)
            hmod = self._kernel32.GetModuleHandleW(None)
            self._hhook = self._user32.SetWindowsHookExW(
                _WH_KEYBOARD_LL, self._proc, hmod, 0,
            )
            if not self._hhook:
                err = ctypes.get_last_error()
                _log.error("SetWindowsHookExW 실패 (err=%d)", err)
                self._proc = None
                return False
            self._installed = True
            _log.info("low-level keyboard hook installed (hhook=%s)", self._hhook)
            return True
        except Exception:
            _log.exception("install() crashed")
            return False

    def uninstall(self) -> None:
        """hook 해제. 이미 해제됐으면 no-op."""
        self._safe_uninstall()

    def is_installed(self) -> bool:
        return self._installed

    # ---------- 내부 ----------
    def _safe_uninstall(self) -> None:
        if not _IS_WIN or not self._installed or self._hhook is None:
            return
        try:
            self._user32.UnhookWindowsHookEx(self._hhook)
            _log.info("low-level keyboard hook uninstalled")
        except Exception:
            _log.exception("UnhookWindowsHookEx crashed")
        finally:
            self._hhook = None
            self._proc = None
            self._installed = False

    def _raw_callback(self, n_code: int, wparam: int, lparam: int) -> int:
        """OS 가 모든 키 입력에 대해 호출. 매칭되는 키만 차단."""
        # 콜백 안에서 절대 raise 금물 — hook 박살남.
        try:
            # nCode < 0 이면 처리하지 말고 그냥 통과 (Microsoft 문서).
            if n_code < 0:
                return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
            if not self._targets:
                return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
            # KEYDOWN 만 처리 (KEYUP 은 통과).
            if wparam not in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
            kbd = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = int(kbd.vkCode)
            # 모디파이어 키 자체의 down 이벤트는 무시 (조합 키의 메인 키만 매칭 대상).
            if vk in _MODIFIER_VKS:
                return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
            mods = _current_modifier_state()
            target = (mods, vk)
            if target in self._targets:
                # 시그널 emit (Qt 가 cross-thread 자동 dispatch — 메인 스레드에서 처리).
                try:
                    self.activated.emit(mods, vk)
                except Exception:
                    _log.exception("activated.emit crashed")
                # 차단 — OS 후속 처리기 (Snipping Tool 등) 에 도달 안 함.
                return 1
            return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
        except Exception:
            # 어떤 예외든 hook 을 떼지 않도록 흡수, 키는 통과시킴.
            _log.exception("_raw_callback crashed — passing through")
            try:
                return self._user32.CallNextHookEx(self._hhook or 0, n_code, wparam, lparam)
            except Exception:
                return 0
