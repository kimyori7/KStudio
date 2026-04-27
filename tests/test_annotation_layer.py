"""AnnotationLayer — 벡터 주석 시스템을 한 레이어 객체로 감쌈."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _blank(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    return img


def test_render_empty_annotation_returns_canvas_size(qtbot):
    from image_editor.layers.annotation_layer import AnnotationLayer
    layer = AnnotationLayer(id=1, name="annot", canvas_size=QSize(100, 80))
    out = layer.render(QSize(100, 80))
    assert out.size() == QSize(100, 80)


def test_render_includes_added_rect(qtbot):
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.items.rect import RectAnnotationItem
    layer = AnnotationLayer(id=1, name="annot", canvas_size=QSize(100, 100))
    rect = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#FF0000"), 3)
    layer.add_item(rect)
    out = layer.render(QSize(100, 100))
    # 사각형 둘레에 빨강 픽셀이 있어야 함
    assert QColor(out.pixel(11, 11)).red() > 0


def test_apply_crop_does_not_lose_items(qtbot):
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.items.rect import RectAnnotationItem
    layer = AnnotationLayer(id=1, name="annot", canvas_size=QSize(100, 100))
    rect = RectAnnotationItem(QRectF(50, 50, 30, 30), QColor("#000000"), 2)
    layer.add_item(rect)
    layer.apply_crop(QRect(40, 40, 50, 50))
    # 아이템은 그대로, scene 좌표계만 shift 됨
    assert len(layer.items()) == 1
    out = layer.render(QSize(50, 50))
    assert out.size() == QSize(50, 50)
