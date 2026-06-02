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


def test_high_dpr_image_normalized_to_full_resolution(qtbot):
    """HiDPI 스크린샷(devicePixelRatio>1)은 device-pixel 전체 해상도로 정규화돼야 한다.

    QScreen.grabWindow().toImage() 는 150% 디스플레이에서 DPR=1.5 인 QImage 를
    돌려준다. 에디터의 모든 좌표(sceneRect, 삭제 fillRect, composite)는 device px
    == scene 단위를 가정하므로, 레이어 픽스맵은 항상 DPR 1.0 이어야 그래픽스
    아이템이 캔버스를 꽉 채우고 삭제 영역이 선택과 일치한다.
    """
    from image_editor.layers.image_layer import ImageLayer
    pix = _solid(60, 40, 0xFFFF0000)
    pix.setDevicePixelRatio(1.5)
    layer = ImageLayer(id=1, name="x", pixmap=pix)
    # 불변식: 픽스맵 DPR 은 1.0 (해상도 손실 없이 device px 그대로 편집)
    assert layer.pixmap.devicePixelRatio() == 1.0
    assert layer.pixmap.size() == QSize(60, 40)
    # 합성 결과도 DPR 1.0 — composed_pixmap 이 캔버스에 1:1 로 매핑된다
    assert layer.composed_pixmap().devicePixelRatio() == 1.0
