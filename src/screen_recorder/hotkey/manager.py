"""Windows RegisterHotKey 기반 전역 단축키 매니저 — OS 레벨에서 키 조합을 가로채므로
다른 앱(브라우저 등)이 해당 조합을 보지 못한다."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from typing import Callable, Dict

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

from .parser import parse_hotkey_to_vk, HotkeyParseError


_user32 = ctypes.windll.user32

# RegisterHotKey 수식자 플래그
_MOD_NOREPEAT = 0x4000

_WM_HOTKEY = 0x0312


class HotkeyManager(QAbstractNativeEventFilter):
    """`RegisterHotKey` 로 등록된 단축키를 `WM_HOTKEY` 메시지로 받아 콜백 디스패치.

    동일 조합을 이미 다른 앱이 선점한 상태이면 등록이 실패할 수 있고,
    그 바인딩은 조용히 스킵된다 (나머지 바인딩은 살아남는다).
    """

    def __init__(self) -> None:
        super().__init__()
        self._ids: Dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._installed = False

    def set_bindings(self, bindings: Dict[str, Callable[[], None]]) -> None:
        """여러 단축키를 한 번에 등록. 빈 문자열 키는 미할당으로 간주해 건너뛴다.

        기존 등록은 먼저 정리된다.
        """
        self.unregister()
        self._ensure_filter_installed()
        for text, cb in bindings.items():
            if not text or not text.strip():
                continue
            try:
                mods, vk = parse_hotkey_to_vk(text)
            except HotkeyParseError:
                continue
            hid = self._next_id
            if _user32.RegisterHotKey(None, hid, mods | _MOD_NOREPEAT, vk):
                self._ids[hid] = cb
                self._next_id += 1

    def register(self, hotkey_text: str, callback: Callable[[], None]) -> None:
        """단일 바인딩 편의 메서드."""
        self.set_bindings({hotkey_text: callback})

    def unregister(self) -> None:
        for hid in list(self._ids.keys()):
            try:
                _user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._ids.clear()

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
                    cb()
                    return True, 0
        except Exception:
            return False, 0
        return False, 0
