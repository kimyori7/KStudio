"""ImageLayer — 원본 픽셀 + 알파 마스크 + 캔버스 내 offset."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, qAlpha


def _solid(w: int, h: int, color: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(color))
    return img


def test_render_no_mask_returns_pixel(qtbot):
    from image_editor.layers.image_layer import ImageLayer
    pix = _solid(40, 30, 0xFFFF0000)  # opaque red
    layer = ImageLayer(id=1, name="bg", pixmap=pix)
    out = layer.render(QSize(40, 30))
    assert out.size() == QSize(40, 30)
    assert QColor(out.pixel(5, 5)).red() == 255


def test_offset_places_layer_inside_canvas(qtbot):
    from image_editor.layers.image_layer import ImageLayer
    pix = _solid(20, 20, 0xFF00FF00)  # opaque green
    layer = ImageLayer(id=1, name="x", pixmap=pix, offset=QPoint(10, 5))
    out = layer.render(QSize(40, 30))
    # (10,5) 안쪽에 초록, (0,0) 은 투명
    assert QColor(out.pixel(15, 10)).green() == 255
    assert qAlpha(out.pixel(0, 0)) == 0


def test_mask_makes_pixels_transparent(qtbot):
    from image_editor.layers.image_layer import ImageLayer
    pix = _solid(20, 20, 0xFFFF0000)  # opaque red
    mask = QImage(20, 20, QImage.Format_Grayscale8)
    mask.fill(0)  # 모두 투명
    layer = ImageLayer(id=1, name="x", pixmap=pix, mask=mask)
    out = layer.render(QSize(20, 20))
    assert qAlpha(out.pixel(10, 10)) == 0


def test_apply_crop_shifts_offset(qtbot):
    from image_editor.layers.image_layer import ImageLayer
    layer = ImageLayer(id=1, name="x", pixmap=_solid(40, 40, 0xFFFFFFFF),
                       offset=QPoint(0, 0))
    layer.apply_crop(QRect(10, 5, 20, 20))
    assert layer.offset == QPoint(-10, -5)
    # 픽셀은 보존
    assert layer.pixmap.size() == QSize(40, 40)


def test_opacity_affects_render(qtbot):
    from image_editor.layers.image_layer import ImageLayer
    pix = _solid(10, 10, 0xFFFF0000)
    layer = ImageLayer(id=1, name="x", pixmap=pix, opacity=0.5)
    out = layer.render(QSize(10, 10))
    a = qAlpha(out.pixel(5, 5))
    assert 100 < a < 160  # 대략 절반
