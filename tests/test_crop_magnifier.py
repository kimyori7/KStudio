"""CropMagnifier — 순수 헬퍼 + 위젯 + CropTool 통합."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, color="#FFFFFF"):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


def _canvas(qtbot, w=100, h=80):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(w, h))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(w, h)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    return canvas


# --- Task 1: 순수 헬퍼 ---

def test_effective_src_size_default():
    from image_editor.tools.crop_magnifier import effective_src_size, SRC_SIZE
    # 큰 이미지: 기본 SRC_SIZE(=15) 그대로
    assert effective_src_size(1000, 800) == SRC_SIZE


def test_effective_src_size_small_image():
    from image_editor.tools.crop_magnifier import effective_src_size
    # 한 변이 SRC_SIZE 보다 작으면 그만큼 줄이고, 최소 1
    assert effective_src_size(10, 200) == 10
    assert effective_src_size(0, 0) == 1


def test_clamp_src_origin_center():
    from image_editor.tools.crop_magnifier import clamp_src_origin
    # 중앙 근처는 center - src//2
    assert clamp_src_origin(50, 40, 15, 100, 80) == (43, 33)


def test_clamp_src_origin_edges():
    from image_editor.tools.crop_magnifier import clamp_src_origin
    # 좌상단 밖으로 못 나감
    assert clamp_src_origin(0, 0, 15, 100, 80) == (0, 0)
    # 우하단: img_w/h - src_size 로 클램프
    assert clamp_src_origin(100, 80, 15, 100, 80) == (85, 65)


def test_loupe_position_default_offset():
    from image_editor.tools.crop_magnifier import loupe_position, _MAG_OFFSET
    # 여유 있는 영역: 커서 우하단으로 offset
    assert loupe_position(10, 10, 500, 500) == (10 + _MAG_OFFSET, 10 + _MAG_OFFSET)


def test_loupe_position_flips_near_edges():
    from image_editor.tools.crop_magnifier import (
        loupe_position, MAG_W, MAG_H, _MAG_OFFSET,
    )
    # 오른쪽/아래 가장자리: 커서 좌상단으로 플립
    x, y = loupe_position(490, 490, 500, 500)
    assert x == 490 - _MAG_OFFSET - MAG_W
    assert y == 490 - _MAG_OFFSET - MAG_H
