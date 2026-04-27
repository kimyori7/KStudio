from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage

from screen_recorder.ui.annotation.scene import AnnotationScene
from screen_recorder.ui.annotation.items.rect import RectAnnotationItem


def _scene():
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    return AnnotationScene(img)


def test_rect_cannot_move_entirely_outside_image(qtbot):
    scene = _scene()
    r = RectAnnotationItem(QRectF(50, 50, 30, 30), QColor("#000"), 2)
    scene.add_annotation(r)
    # 이미지는 0,0,200,200. 멀리 이동해도 최소 일부는 안에 있어야 함
    r.setPos(QPointF(500, 500))
    scene_rect = scene.sceneRect()
    item_scene_rect = r.mapToScene(r.boundingRect()).boundingRect()
    assert scene_rect.intersects(item_scene_rect)
