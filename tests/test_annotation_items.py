from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsScene

from image_editor.items.rect import RectAnnotationItem


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


from PySide6.QtCore import QPointF
from image_editor.items.arrow import ArrowAnnotationItem


def test_arrow_item_holds_endpoints(qtbot):
    a = ArrowAnnotationItem(QPointF(10, 20), QPointF(100, 80), QColor("#000"), thickness_step=2)
    assert a.start() == QPointF(10, 20)
    assert a.end() == QPointF(100, 80)


def test_arrow_item_bounding_rect_encloses_endpoints(qtbot):
    a = ArrowAnnotationItem(QPointF(0, 0), QPointF(100, 50), QColor("#000"), thickness_step=4)
    br = a.boundingRect()
    # 양 끝 + stroke padding + 화살표 머리 여유
    assert br.contains(QPointF(0, 0))
    assert br.contains(QPointF(100, 50))


def test_arrow_set_endpoints(qtbot):
    a = ArrowAnnotationItem(QPointF(0, 0), QPointF(10, 10), QColor("#000"), thickness_step=1)
    a.set_start(QPointF(5, 5))
    a.set_end(QPointF(50, 50))
    assert a.start() == QPointF(5, 5)
    assert a.end() == QPointF(50, 50)


from image_editor.items.text import TextAnnotationItem


def test_text_item_holds_pos_and_text(qtbot):
    t = TextAnnotationItem(QPointF(20, 30), "안녕", QColor("#000"))
    assert t.pos_f() == QPointF(20, 30)
    assert t.text() == "안녕"


def test_text_item_set_text(qtbot):
    t = TextAnnotationItem(QPointF(0, 0), "a", QColor("#000"))
    t.set_text("hello")
    assert t.text() == "hello"


def test_text_item_set_color(qtbot):
    t = TextAnnotationItem(QPointF(0, 0), "a", QColor("#FF0000"))
    t.set_color(QColor("#00FF00"))
    assert t.color() == QColor("#00FF00")


from PySide6.QtWidgets import QGraphicsScene


def test_rect_selecting_shows_8_handles(qtbot):
    scene = QGraphicsScene()
    item = RectAnnotationItem(QRectF(0, 0, 100, 50), QColor("#000"), 2)
    scene.addItem(item)
    item.setSelected(True)
    handles = [c for c in item.childItems() if c.data(0) == "handle"]
    assert len(handles) == 8


def test_rect_deselecting_removes_handles(qtbot):
    scene = QGraphicsScene()
    item = RectAnnotationItem(QRectF(0, 0, 100, 50), QColor("#000"), 2)
    scene.addItem(item)
    item.setSelected(True)
    item.setSelected(False)
    handles = [c for c in item.childItems() if c.data(0) == "handle"]
    assert len(handles) == 0


def test_arrow_selecting_shows_2_handles(qtbot):
    scene = QGraphicsScene()
    item = ArrowAnnotationItem(QPointF(0, 0), QPointF(100, 100), QColor("#000"), 2)
    scene.addItem(item)
    item.setSelected(True)
    handles = [c for c in item.childItems() if c.data(0) == "handle"]
    assert len(handles) == 2
