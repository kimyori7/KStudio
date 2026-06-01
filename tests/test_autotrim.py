"""compute_trim_rect — 균일/투명 테두리 감지 → 내용물 바운딩박스. + CropCommand 통합."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter


def _img(w: int, h: int, bg, content_rect=None, content=QColor("red")) -> QImage:
    """bg 색으로 채운 w×h 이미지에 content_rect(x,y,w,h) 만큼 content 색을 칠한다."""
    im = QImage(w, h, QImage.Format_ARGB32)
    im.fill(bg if isinstance(bg, QColor) else QColor(bg))
    if content_rect is not None:
        x, y, rw, rh = content_rect
        p = QPainter(im)
        p.fillRect(QRect(x, y, rw, rh), content)
        p.end()
    return im


def test_dark_border_trims_to_content():
    from image_editor.operations.autotrim import compute_trim_rect
    # 80×40 어두운 배경, (20,10)~(60,30) 빨강 내용물
    im = _img(80, 40, "#1b1b1b", content_rect=(20, 10, 40, 20))
    rect = compute_trim_rect(im)
    assert rect == QRect(20, 10, 40, 20)


def test_transparent_border_trims_to_content():
    from image_editor.operations.autotrim import compute_trim_rect
    im = _img(80, 40, Qt.transparent, content_rect=(15, 8, 50, 24))
    rect = compute_trim_rect(im)
    assert rect == QRect(15, 8, 50, 24)


def test_content_touching_left_edge_keeps_that_edge():
    from image_editor.operations.autotrim import compute_trim_rect
    # 내용물이 x=0(왼쪽 끝)에 닿음 → 왼쪽은 안 깎이고 위/아래/오른쪽만 트림
    im = _img(80, 40, "#1b1b1b", content_rect=(0, 10, 40, 20))
    rect = compute_trim_rect(im)
    assert rect == QRect(0, 10, 40, 20)


def test_single_pixel_noise_is_ignored():
    from image_editor.operations.autotrim import compute_trim_rect
    # 단일 노이즈 픽셀을 무시하려면 그 픽셀이 속한 행/열 길이가 >=100 이어야 한다
    # (min_bg_fraction=0.99 → 1/L <= 0.01). 120×120 에서 (5,5) 점 1개는 행·열 모두
    # 119/120=0.9917 >= 0.99 → 배경으로 인정되어 무시된다.
    im = _img(120, 120, "#1b1b1b", content_rect=(40, 40, 40, 40))
    im.setPixelColor(5, 5, QColor("yellow"))
    rect = compute_trim_rect(im)
    assert rect == QRect(40, 40, 40, 40)


def test_corners_disagree_returns_none():
    from image_editor.operations.autotrim import compute_trim_rect
    im = QImage(40, 40, QImage.Format_ARGB32)
    p = QPainter(im)
    p.fillRect(QRect(0, 0, 20, 20), QColor("#1b1b1b"))    # TL 어둠
    p.fillRect(QRect(20, 0, 20, 20), QColor("white"))     # TR 흰색
    p.fillRect(QRect(0, 20, 20, 20), QColor("blue"))      # BL 파랑
    p.fillRect(QRect(20, 20, 20, 20), QColor("green"))    # BR 초록
    p.end()
    assert compute_trim_rect(im) is None


def test_uniform_image_returns_none():
    from image_editor.operations.autotrim import compute_trim_rect
    im = _img(40, 40, "#1b1b1b")          # 전체가 배경, 내용물 없음
    assert compute_trim_rect(im) is None


def test_no_margin_returns_none():
    from image_editor.operations.autotrim import compute_trim_rect
    # 내용물이 캔버스 전체를 채움 → 코너가 빨강으로 일치하지만 자를 여백 없음 → None
    im = _img(40, 40, "red", content_rect=(0, 0, 40, 40))
    assert compute_trim_rect(im) is None


def test_tolerance_treats_near_bg_as_background():
    from image_editor.operations.autotrim import compute_trim_rect
    # 배경 #202020, 테두리에 #282828(채널차 8 < tol12) 노이즈가 행 전체에 깔려도 배경으로 봄
    im = _img(80, 40, "#202020", content_rect=(20, 10, 40, 20))
    p = QPainter(im)
    p.fillRect(QRect(0, 0, 80, 3), QColor("#282828"))   # 위 테두리 살짝 밝게
    p.end()
    rect = compute_trim_rect(im, tolerance=12)
    assert rect == QRect(20, 10, 40, 20)


def test_integration_crop_command_resizes_and_undo_restores(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.autotrim import compute_trim_rect
    from image_editor.operations.crop import CropCommand
    im = _img(80, 40, "#1b1b1b", content_rect=(20, 10, 40, 20))
    stack = LayerStack(QSize(80, 40))
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=im, offset=QPoint(0, 0)))
    rect = compute_trim_rect(im)
    assert rect == QRect(20, 10, 40, 20)
    cmd = CropCommand(stack, rect)
    cmd.redo()
    assert stack.canvas_size == QSize(40, 20)
    cmd.undo()
    assert stack.canvas_size == QSize(80, 40)
