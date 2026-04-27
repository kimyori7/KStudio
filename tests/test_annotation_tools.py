from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage

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
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2, shift_held=lambda: False)
    tool.mouse_press(scene, QPointF(10, 20))
    tool.mouse_move(scene, QPointF(60, 70))
    tool.mouse_release(scene, QPointF(60, 70))

    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 1
    r = rects[0].rect()
    assert r.x() == 10 and r.y() == 20
    assert r.width() == 50 and r.height() == 50


def test_rect_tool_tiny_drag_is_cancelled(qtbot):
    scene = _scene()
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2, shift_held=lambda: False)
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(13, 12))  # 3×2 — 5×5 이하
    tool.mouse_release(scene, QPointF(13, 12))
    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 0


def test_rect_tool_shift_forces_square(qtbot):
    scene = _scene()
    tool = RectTool(color=QColor("#000"), thickness_step=1, shift_held=lambda: True)
    tool.mouse_press(scene, QPointF(0, 0))
    tool.mouse_move(scene, QPointF(80, 40))
    tool.mouse_release(scene, QPointF(80, 40))
    r = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)][0]
    # shift → 정사각형, 짧은 변 기준 (40)
    assert r.rect().width() == 40
    assert r.rect().height() == 40
