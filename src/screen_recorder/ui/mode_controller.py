"""영상 / 이미지 모드 상태 관리."""
from __future__ import annotations
from enum import Enum

from PySide6.QtCore import QObject, Signal


class AppMode(Enum):
    VIDEO = "video"
    IMAGE = "image"


class ModeController(QObject):
    mode_changed = Signal(object)   # AppMode

    def __init__(self) -> None:
        super().__init__()
        self._mode = AppMode.IMAGE

    def mode(self) -> AppMode:
        return self._mode

    def set_mode(self, mode: AppMode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self.mode_changed.emit(mode)
