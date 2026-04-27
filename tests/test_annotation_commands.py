from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QUndoStack

from screen_recorder.ui.annotation.scene import AnnotationScene
from screen_recorder.ui.annotation.items.rect import RectAnnotationItem
from screen_recorder.ui.annotation.commands import (
    AddAnnotationCommand,
    RemoveAnnotationCommand,
    MoveAnnotationCommand,
    ChangeRectCommand,
    ChangeColorCommand,
)


def _scene() -> AnnotationScene:
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    return AnnotationScene(img)


def test_add_command_undo_redo(qtbot):
    scene = _scene()
    stack = QUndoStack()
    item = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#000"), 2)
    stack.push(AddAnnotationCommand(scene, item))
    assert item in scene.annotations()
    stack.undo()
    assert item not in scene.annotations()
    stack.redo()
    assert item in scene.annotations()


def test_remove_command(qtbot):
    scene = _scene()
    stack = QUndoStack()
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    scene.add_annotation(item)
    stack.push(RemoveAnnotationCommand(scene, item))
    assert item not in scene.annotations()
    stack.undo()
    assert item in scene.annotations()


def test_move_command(qtbot):
    scene = _scene()
    stack = QUndoStack()
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    scene.add_annotation(item)
    stack.push(MoveAnnotationCommand(item, QPointF(0, 0), QPointF(50, 60)))
    assert item.pos() == QPointF(50, 60)
    stack.undo()
    assert item.pos() == QPointF(0, 0)


def test_change_rect_command(qtbot):
    scene = _scene()
    stack = QUndoStack()
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    scene.add_annotation(item)
    stack.push(ChangeRectCommand(item, QRectF(0, 0, 10, 10), QRectF(5, 5, 20, 20)))
    assert item.rect() == QRectF(5, 5, 20, 20)
    stack.undo()
    assert item.rect() == QRectF(0, 0, 10, 10)


def test_change_color_command(qtbot):
    scene = _scene()
    stack = QUndoStack()
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000000"), 2)
    scene.add_annotation(item)
    stack.push(ChangeColorCommand(item, QColor("#000000"), QColor("#FF0000")))
    assert item.color() == QColor("#FF0000")
    stack.undo()
    assert item.color() == QColor("#000000")
