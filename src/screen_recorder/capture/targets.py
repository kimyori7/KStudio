"""캡처 대상 추상화: 매 프레임 호출되는 current_rect() 제공."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def as_dxcam_region(self) -> tuple[int, int, int, int]:
        """dxcam은 (left, top, right, bottom)."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


class CaptureTarget(Protocol):
    def current_rect(self) -> Optional[Rect]: ...
    def label(self) -> str: ...


class FullScreenTarget:
    def __init__(self, monitor_index: int = 0):
        self.monitor_index = monitor_index

    def current_rect(self) -> Optional[Rect]:
        return self._get_monitor_rect()

    def _get_monitor_rect(self) -> Rect:
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        idx = min(self.monitor_index, len(screens) - 1)
        g = screens[idx].geometry()
        return Rect(g.x(), g.y(), g.width(), g.height())

    def label(self) -> str:
        return "fullscreen"


class RegionTarget:
    def __init__(self, rect: Rect):
        self.rect = rect

    def current_rect(self) -> Optional[Rect]:
        return self.rect

    def label(self) -> str:
        return "region"


class WindowTarget:
    """pygetwindow Window 객체를 받아 매번 좌표 갱신."""
    def __init__(self, window):
        self.window = window

    def current_rect(self) -> Optional[Rect]:
        if self.window.isMinimized:
            return None
        return Rect(
            int(self.window.left),
            int(self.window.top),
            int(self.window.width),
            int(self.window.height),
        )

    def label(self) -> str:
        return "window"
