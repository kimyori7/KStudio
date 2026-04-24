from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsScene

from screen_recorder.ui.annotation.items.rect import RectAnnotationItem


def test_rect_item_holds_rect_color_thickness(qtbot):
    item = RectAnnotationItem(QRectF(10, 20, 100, 50), QColor("#E53935"), thickness_step=2)
    assert item.rect() == QRectF(10, 20, 100, 50)
    assert item.color() == QColor("#E53935")
    assert item.thickness_step() == 2


def test_rect_item_bounding_rect_includes_stroke(qtbot):
    item = RectAnnotationItem(QRectF(0, 0, 100, 50), QColor("#000000"), thickness_step=4)
    br = item.boundingRect()
    # stroke half-width 4px(8/2) padding 필요
    assert br.x() <= -4
    assert br.y() <= -4
    assert br.width() >= 108
    assert br.height() >= 58


def test_rect_item_set_rect_updates(qtbot):
    scene = QGraphicsScene()
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), thickness_step=1)
    scene.addItem(item)
    item.set_rect(QRectF(5, 5, 50, 50))
    assert item.rect() == QRectF(5, 5, 50, 50)


def test_rect_item_set_color_updates(qtbot):
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), thickness_step=1)
    item.set_color(QColor("#FF0000"))
    assert item.color() == QColor("#FF0000")


def test_rect_item_set_thickness_updates(qtbot):
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), thickness_step=1)
    item.set_thickness_step(3)
    assert item.thickness_step() == 3
