from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QUndoStack

from screen_recorder.ui.annotation.scene import AnnotationScene
from screen_recorder.ui.annotation.items.rect import RectAnnotationItem
from screen_recorder.ui.annotation.tools.select import SelectTool


def _scene():
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    return AnnotationScene(img)


def test_select_tool_click_empty_clears_selection(qtbot):
    scene = _scene()
    r = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#000"), 2)
    scene.add_annotation(r)
    r.setSelected(True)

    tool = SelectTool()
    tool.mouse_press(scene, QPointF(150, 150))  # 빈 곳
    assert r.isSelected() is False


def test_select_tool_click_on_item_selects_it(qtbot):
    scene = _scene()
    r = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#000"), 2)
    scene.add_annotation(r)

    tool = SelectTool()
    tool.mouse_press(scene, QPointF(20, 20))
    assert r.isSelected() is True


from screen_recorder.ui.annotation.tools.rect import RectTool


def test_rect_tool_drag_creates_rect(qtbot):
    scene = _scene()
    stack = QUndoStack()
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2,
                    shift_held=lambda: False, undo_stack=stack)
    tool.mouse_press(scene, QPointF(10, 20))
    tool.mouse_move(scene, QPointF(60, 70))
    tool.mouse_release(scene, QPointF(60, 70))

    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 1
    r = rects[0].rect()
    assert r.x() == 10 and r.y() == 20
    assert r.width() == 50 and r.height() == 50
    assert stack.count() == 1  # AddAnnotationCommand 푸시됨


def test_rect_tool_tiny_drag_is_cancelled(qtbot):
    scene = _scene()
    stack = QUndoStack()
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2,
                    shift_held=lambda: False, undo_stack=stack)
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(13, 12))
    tool.mouse_release(scene, QPointF(13, 12))
    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 0
    assert stack.count() == 0


def test_rect_tool_shift_forces_square(qtbot):
    scene = _scene()
    tool = RectTool(color=QColor("#000"), thickness_step=1,
                    shift_held=lambda: True, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(0, 0))
    tool.mouse_move(scene, QPointF(80, 40))
    tool.mouse_release(scene, QPointF(80, 40))
    r = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)][0]
    assert r.rect().width() == 40
    assert r.rect().height() == 40


from screen_recorder.ui.annotation.tools.arrow import ArrowTool
from screen_recorder.ui.annotation.items.arrow import ArrowAnnotationItem


def test_arrow_tool_drag_creates_arrow(qtbot):
    scene = _scene()
    tool = ArrowTool(color=QColor("#000"), thickness_step=2,
                     shift_held=lambda: False, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(100, 50))
    tool.mouse_release(scene, QPointF(100, 50))
    arrows = [a for a in scene.annotations() if isinstance(a, ArrowAnnotationItem)]
    assert len(arrows) == 1
    assert arrows[0].start() == QPointF(10, 10)
    assert arrows[0].end() == QPointF(100, 50)


def test_arrow_tool_tiny_drag_cancelled(qtbot):
    scene = _scene()
    tool = ArrowTool(color=QColor("#000"), thickness_step=2,
                     shift_held=lambda: False, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(11, 11))
    tool.mouse_release(scene, QPointF(11, 11))
    assert len([a for a in scene.annotations() if isinstance(a, ArrowAnnotationItem)]) == 0


from screen_recorder.ui.annotation.tools.text import TextTool
from screen_recorder.ui.annotation.items.text import TextAnnotationItem


def test_text_tool_click_creates_editing_text(qtbot):
    scene = _scene()
    tool = TextTool(color=QColor("#000"), undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(40, 40))
    tool.mouse_release(scene, QPointF(40, 40))
    texts = [a for a in scene.annotations() if isinstance(a, TextAnnotationItem)]
    assert len(texts) == 1
    assert texts[0].pos_f() == QPointF(40, 40)


def test_text_tool_empty_text_is_cleaned_on_commit(qtbot):
    scene = _scene()
    tool = TextTool(color=QColor("#000"), undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(40, 40))
    tool.mouse_release(scene, QPointF(40, 40))
    tool.commit_active(scene)  # 빈 채로 확정
    assert len([a for a in scene.annotations() if isinstance(a, TextAnnotationItem)]) == 0
