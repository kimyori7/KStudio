from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QImage, QColor

from image_editor.scene import AnnotationScene
from image_editor.items.rect import RectAnnotationItem
from image_editor.items.arrow import ArrowAnnotationItem


def _img(w=100, h=80) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(200, 200, 200))
    return img


def test_scene_starts_with_background(qtbot):
    img = _img()
    scene = AnnotationScene(img)
    assert scene.sceneRect() == QRectF(0, 0, 100, 80)
    assert scene.background_image().width() == 100


def test_add_annotation_is_selectable(qtbot):
    scene = AnnotationScene(_img())
    r = RectAnnotationItem(QRectF(5, 5, 20, 20), QColor("#000"), 2)
    scene.add_annotation(r)
    assert r in scene.annotations()


def test_single_selection_enforced(qtbot):
    scene = AnnotationScene(_img())
    r1 = RectAnnotationItem(QRectF(5, 5, 20, 20), QColor("#000"), 2)
    r2 = RectAnnotationItem(QRectF(30, 30, 20, 20), QColor("#000"), 2)
    scene.add_annotation(r1)
    scene.add_annotation(r2)
    r1.setSelected(True)
    r2.setSelected(True)
    selected = [a for a in scene.annotations() if a.isSelected()]
    assert len(selected) == 1
    assert selected[0] is r2  # 나중에 선택한 게 유일 선택


def test_remove_annotation(qtbot):
    scene = AnnotationScene(_img())
    r = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    scene.add_annotation(r)
    scene.remove_annotation(r)
    assert r not in scene.annotations()


def test_render_composite_returns_same_size(qtbot):
    img = _img(120, 90)
    scene = AnnotationScene(img)
    out = scene.render_composite()
    assert out.width() == 120
    assert out.height() == 90
