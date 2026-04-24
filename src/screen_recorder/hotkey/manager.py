"""pynput 전역 단축키 래퍼 (다중 바인딩 지원)."""
from __future__ import annotations
from typing import Callable, Dict

try:
    from pynput.keyboard import GlobalHotKeys  # type: ignore
except ImportError:
    GlobalHotKeys = None  # type: ignore

from .parser import parse_hotkey, HotkeyParseError


class HotkeyManager:
    def __init__(self) -> None:
        self._listener = None

    def set_bindings(self, bindings: Dict[str, Callable[[], None]]) -> None:
        """여러 단축키를 한 번에 등록. 빈 문자열 키는 건너뛴다 (미할당 의미).

        이전 리스너는 정리되고 새 리스너 하나가 만들어진다.
        파싱 불가능한 단축키는 조용히 무시한다 — 하나가 깨져도 나머지는 살림.
        """
        self.unregister()
        parsed: Dict[str, Callable[[], None]] = {}
        for text, cb in bindings.items():
            if not text or not text.strip():
                continue
            try:
                parsed[parse_hotkey(text)] = cb
            except HotkeyParseError:
                continue
        if not parsed:
            return
        if GlobalHotKeys is None:
            return
        self._listener = GlobalHotKeys(parsed)
        self._listener.start()

    def register(self, hotkey_text: str, callback: Callable[[], None]) -> None:
        """단일 바인딩 편의 메서드 (하위 호환)."""
        self.set_bindings({hotkey_text: callback})

    def unregister(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
