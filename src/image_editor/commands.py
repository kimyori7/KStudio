"""주석 편집 동작의 Undo/Redo 단위."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QUndoCommand
from PySide6.QtWidgets import QGraphicsItem

from .items.arrow import ArrowAnnotationItem
from .items.rect import RectAnnotationItem
from .items.text import TextAnnotationItem
from .scene import AnnotationScene


class AddAnnotationCommand(QUndoCommand):
    def __init__(self, scene: AnnotationScene, item: QGraphicsItem) -> None:
        super().__init__("주석 추가")
        self._scene = scene
        self._item = item

    def redo(self) -> None:
        if self._item.scene() is None:
            self._scene.add_annotation(self._item)

    def undo(self) -> None:
        if self._item.scene() is self._scene:
            self._scene.remove_annotation(self._item)


class RemoveAnnotationCommand(QUndoCommand):
    def __init__(self, scene: AnnotationScene, item: QGraphicsItem) -> None:
        super().__init__("주석 삭제")
        self._scene = scene
        self._item = item

    def redo(self) -> None:
        if self._item.scene() is self._scene:
            self._scene.remove_annotation(self._item)

    def undo(self) -> None:
        if self._item.scene() is None:
            self._scene.add_annotation(self._item)


class MoveAnnotationCommand(QUndoCommand):
    def __init__(self, item: QGraphicsItem, old_pos: QPointF, new_pos: QPointF) -> None:
        super().__init__("주석 이동")
        self._item = item
        self._old = QPointF(old_pos)
        self._new = QPointF(new_pos)

    def redo(self) -> None:
        self._item.setPos(self._new)

    def undo(self) -> None:
        self._item.setPos(self._old)


class ChangeRectCommand(QUndoCommand):
    def __init__(self, item: RectAnnotationItem, old: QRectF, new: QRectF) -> None:
        super().__init__("사각형 크기 변경")
        self._item = item
        self._old = QRectF(old)
        self._new = QRectF(new)

    def redo(self) -> None:
        self._item.set_rect(self._new)
        self._item._reposition_handles()

    def undo(self) -> None:
        self._item.set_rect(self._old)
        self._item._reposition_handles()


class ChangeArrowEndpointsCommand(QUndoCommand):
    def __init__(
        self,
        item: ArrowAnnotationItem,
        old_start: QPointF, old_end: QPointF,
        new_start: QPointF, new_end: QPointF,
    ) -> None:
        super().__init__("화살표 끝점 변경")
        self._item = item
        self._os = QPointF(old_start); self._oe = QPointF(old_end)
        self._ns = QPointF(new_start); self._ne = QPointF(new_end)

    def redo(self) -> None:
        self._item.set_start(self._ns)
        self._item.set_end(self._ne)
        self._item._reposition_handles()

    def undo(self) -> None:
        self._item.set_start(self._os)
        self._item.set_end(self._oe)
        self._item._reposition_handles()


class ChangeColorCommand(QUndoCommand):
    def __init__(self, item, old: QColor, new: QColor) -> None:
        super().__init__("색상 변경")
        self._item = item
        self._old = QColor(old)
        self._new = QColor(new)

    def redo(self) -> None:
        self._item.set_color(self._new)

    def undo(self) -> None:
        self._item.set_color(self._old)


class ChangeThicknessCommand(QUndoCommand):
    def __init__(self, item, old: int, new: int) -> None:
        super().__init__("두께 변경")
        self._item = item
        self._old = int(old)
        self._new = int(new)

    def redo(self) -> None:
        self._item.set_thickness_step(self._new)

    def undo(self) -> None:
        self._item.set_thickness_step(self._old)


class EditTextCommand(QUndoCommand):
    def __init__(self, item: TextAnnotationItem, old: str, new: str) -> None:
        super().__init__("텍스트 편집")
        self._item = item
        self._old = old
        self._new = new

    def redo(self) -> None:
        self._item.set_text(self._new)

    def undo(self) -> None:
        self._item.set_text(self._old)
