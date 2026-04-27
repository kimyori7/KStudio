"""레이어 추상 베이스."""
from __future__ import annotations
from abc import ABC, abstractmethod

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImage


class Layer(ABC):
    def __init__(self, id: int, name: str, *, visible: bool = True, opacity: float = 1.0) -> None:
        self.id = id
        self.name = name
        self.visible = visible
        self.opacity = opacity

    @abstractmethod
    def render(self, canvas_size: QSize) -> QImage:
        """이 레이어를 캔버스 크기의 ARGB32 QImage 로 렌더링."""

    @abstractmethod
    def apply_crop(self, rect: QRect) -> None:
        """캔버스 좌표계에서의 crop rect 가 적용될 때 호출됨.
        레이어 자체 좌표계는 유지하되 offset 만 갱신하면 됨 (비파괴)."""
