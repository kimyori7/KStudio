"""pynput 전역 단축키 래퍼."""
from __future__ import annotations
from typing import Callable, Optional

try:
    from pynput.keyboard import GlobalHotKeys  # type: ignore
except ImportError:
    GlobalHotKeys = None  # type: ignore

from .parser import parse_hotkey


class HotkeyManager:
    def __init__(self) -> None:
        self._listener = None

    def register(self, hotkey_text: str, callback: Callable[[], None]) -> None:
        self.unregister()
        binding = {parse_hotkey(hotkey_text): callback}
        self._listener = GlobalHotKeys(binding)
        self._listener.start()

    def unregister(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
