"""주석 아이템 공통 기반 (색상/두께 보관)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


class AnnotationProperties(QObject):
    """색상/두께 변경을 시그널로 알리는 데이터 보관자.

    QGraphicsItem 이 QObject 상속 아님이라 시그널을 직접 붙일 수 없어 분리.
    각 AnnotationItem 이 이 객체를 자기 속성으로 보유.
    """

    changed = Signal()

    def __init__(self, color: QColor, thickness_step: int) -> None:
        super().__init__()
        self._color = QColor(color)
        self._thickness_step = int(thickness_step)

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        if self._color != color:
            self._color = QColor(color)
            self.changed.emit()

    def thickness_step(self) -> int:
        return self._thickness_step

    def set_thickness_step(self, step: int) -> None:
        if self._thickness_step != step:
            self._thickness_step = int(step)
            self.changed.emit()
