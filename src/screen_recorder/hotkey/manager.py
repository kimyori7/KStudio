"""Windows RegisterHotKey 기반 전역 단축키 매니저 — OS 레벨에서 키 조합을 가로채므로
다른 앱(브라우저 등)이 해당 조합을 보지 못한다."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import logging
from typing import Callable, Dict, Optional

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication, QWidget

from .parser import parse_hotkey_to_vk, HotkeyParseError


_log = logging.getLogger(__name__)

_user32 = ctypes.windll.user32
# 시그니처 명시 — Windows HWND(LP_VOID)를 정확히 넘기기 위해
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_kernel32 = ctypes.windll.kernel32
_kernel32.GetLastError.restype = wintypes.DWORD

# RegisterHotKey 수식자 플래그
_MOD_NOREPEAT = 0x4000

_WM_HOTKEY = 0x0312


class HotkeyManager(QAbstractNativeEventFilter):
    """`RegisterHotKey` 로 등록된 단축키를 `WM_HOTKEY` 메시지로 받아 콜백 디스패치.

    동일 조합을 이미 다른 앱이 선점한 상태이면 등록이 실패할 수 있고,
    그 바인딩은 조용히 스킵된다 (나머지 바인딩은 살아남는다).

    `host_widget` 을 받으면 해당 창의 HWND 를 RegisterHotKey 에 넘겨 WM_HOTKEY 메시지가
    창 큐로 들어오도록 한다. (HWND=NULL 로 등록하면 스레드 큐로만 가서 Qt 의 nativeEventFilter
    에서 놓칠 수 있다.)
    """

    def __init__(self, host_widget: Optional[QWidget] = None) -> None:
        super().__init__()
        self._host = host_widget
        self._ids: Dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._installed = False
        # Low-level hook 은 OS 시스템 단축키(Win+Shift+S 등)용 fallback. 사용자가
        # intercept_system_keys 토글을 켤 때만 활성화.
        self._ll_hook = None
        self._ll_callbacks: Dict[tuple[int, int], Callable[[], None]] = {}
        self._intercept_enabled = False

    def set_host_widget(self, host: QWidget) -> None:
        """HWND 를 나중에 주입할 때 사용."""
        self._host = host

    def _hwnd(self) -> int:
        if self._host is None:
            return 0
        try:
            return int(self._host.winId())
        except Exception:
            return 0

    def set_intercept_enabled(self, enabled: bool) -> None:
        """OS 시스템 단축키 가로채기 토글. set_bindings 다음에 호출하거나 호출 후
        다시 set_bindings 해야 fallback 매핑이 LL hook 으로 등록됨."""
        if enabled and self._ll_hook is None:
            from .low_level_hook import LowLevelKeyboardHook
            self._ll_hook = LowLevelKeyboardHook()
            self._ll_hook.activated.connect(self._on_ll_activated)
        if self._ll_hook is not None:
            if enabled and not self._ll_hook.is_installed():
                self._ll_hook.install()
            elif not enabled and self._ll_hook.is_installed():
                self._ll_hook.uninstall()
                self._ll_callbacks.clear()
        self._intercept_enabled = enabled

    def set_bindings(self, bindings: Dict[str, Callable[[], None]]) -> None:
        """여러 단축키를 한 번에 등록. 빈 문자열 키는 미할당으로 간주해 건너뛴다.

        기존 등록은 먼저 정리된다. RegisterHotKey 가 실패한 키는 intercept_enabled 가
        켜진 경우 low-level hook 의 target 으로 추가 — Win+Shift+S 같은 OS 시스템
        단축키도 가로채진다.
        """
        self.unregister()
        self._ll_callbacks.clear()
        self._ensure_filter_installed()
        hwnd = self._hwnd()
        for text, cb in bindings.items():
            if not text or not text.strip():
                continue
            try:
                mods, vk = parse_hotkey_to_vk(text)
            except HotkeyParseError as e:
                _log.warning("hotkey parse failed for %r: %s", text, e)
                continue
            hid = self._next_id
            ok = _user32.RegisterHotKey(hwnd, hid, mods | _MOD_NOREPEAT, vk)
            if ok:
                self._ids[hid] = cb
                _log.info("RegisterHotKey OK: %r → id=%d, mods=0x%04x, vk=0x%02x", text, hid, mods, vk)
                self._next_id += 1
            else:
                err = _kernel32.GetLastError()
                _log.warning(
                    "RegisterHotKey FAILED: %r (err=%d) — 다른 앱이 이 조합을 선점하고 있을 수 있음",
                    text, err,
                )
                # 토글이 켜져 있으면 low-level hook 으로 fallback (OS 시스템 단축키 케이스).
                if self._intercept_enabled and self._ll_hook is not None:
                    self._ll_callbacks[(mods, vk)] = cb
                    _log.info("LL hook fallback registered: %r (mods=0x%04x, vk=0x%02x)",
                              text, mods, vk)
                # id 는 안 증가 (재사용 가능)
        # LL hook 의 target 갱신.
        if self._ll_hook is not None:
            self._ll_hook.set_targets(self._ll_callbacks.keys())

    def register(self, hotkey_text: str, callback: Callable[[], None]) -> None:
        """단일 바인딩 편의 메서드."""
        self.set_bindings({hotkey_text: callback})

    def unregister(self) -> None:
        hwnd = self._hwnd()
        for hid in list(self._ids.keys()):
            try:
                _user32.UnregisterHotKey(hwnd, hid)
            except Exception:
                pass
        self._ids.clear()
        # LL hook 의 target 도 비움 (콜백 매핑은 set_bindings 에서 다시 채움).
        self._ll_callbacks.clear()
        if self._ll_hook is not None:
            self._ll_hook.set_targets([])

    def _on_ll_activated(self, mods: int, vk: int) -> None:
        cb = self._ll_callbacks.get((int(mods), int(vk)))
        if cb is None:
            return
        try:
            cb()
        except Exception:
            _log.exception("LL hook callback crashed")

    def shutdown(self) -> None:
        """앱 종료 시 호출 — LL hook 도 안전 해제."""
        self.unregister()
        if self._ll_hook is not None:
            self._ll_hook.uninstall()

    def _ensure_filter_installed(self) -> None:
        if self._installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self)
            self._installed = True

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type != b"windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY:
                cb = self._ids.get(int(msg.wParam))
                if cb is not None:
                    _log.debug("WM_HOTKEY received id=%d", int(msg.wParam))
                    cb()
                    return True, 0
        except Exception:
            return False, 0
        return False, 0
