"""주석 아이템 공통 기반 (색상/두께 보관)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Signal
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


def clamp_position_to_scene(
    item_local_bounding: QRectF,
    requested_pos: QPointF,
    scene_rect: QRectF,
    margin: float = 10.0,
) -> QPointF:
    """아이템이 씬(이미지) 영역과 최소 `margin` 픽셀은 겹치도록 position 을 조정.

    아이템 좌표계는 local → scene 변환 시 item.pos() + local_bounding 이 씬 bbox.
    """
    new_scene_bbox = item_local_bounding.translated(requested_pos)

    intersect = new_scene_bbox.intersected(scene_rect)
    if intersect.width() >= margin and intersect.height() >= margin:
        return requested_pos

    x = requested_pos.x()
    if new_scene_bbox.right() < scene_rect.left() + margin:
        x = scene_rect.left() + margin - item_local_bounding.right()
    elif new_scene_bbox.left() > scene_rect.right() - margin:
        x = scene_rect.right() - margin - item_local_bounding.left()

    y = requested_pos.y()
    if new_scene_bbox.bottom() < scene_rect.top() + margin:
        y = scene_rect.top() + margin - item_local_bounding.bottom()
    elif new_scene_bbox.top() > scene_rect.bottom() - margin:
        y = scene_rect.bottom() - margin - item_local_bounding.top()

    return QPointF(x, y)
