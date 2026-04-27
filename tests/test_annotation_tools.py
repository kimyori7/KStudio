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
