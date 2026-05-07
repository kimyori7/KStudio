"""caption_renderer — preview/PNG 공유 헬퍼."""
from screen_recorder.effects.types.caption import (
    CaptionEffect, Fade, Position,
)
from screen_recorder.ui.video.caption_renderer import (
    fade_alpha, anchor_xy, draw_caption,
)


def _caption(in_ms=1000, out_ms=4000, fi=300, fo=300, **kw):
    return CaptionEffect(in_ms=in_ms, out_ms=out_ms,
                         fade=Fade(in_ms=fi, out_ms=fo), **kw)


def test_fade_alpha_before_in_returns_zero():
    assert fade_alpha(_caption(), 999) == 0.0


def test_fade_alpha_after_out_returns_zero():
    assert fade_alpha(_caption(), 4001) == 0.0


def test_fade_alpha_full_in_middle():
    # in 1000~4000, fade 300/300. t=2000 (한가운데) → 1.0
    assert fade_alpha(_caption(), 2000) == 1.0


def test_fade_alpha_linear_during_fade_in():
    # t=1150 → 150/300 = 0.5
    a = fade_alpha(_caption(), 1150)
    assert abs(a - 0.5) < 0.01


def test_anchor_xy_top_left():
    pos = Position(anchor="top-left")
    x, y = anchor_xy(pos, text_w=100, text_h=40, pad=8, surface_w=1920, surface_h=1080)
    assert x == 8
    # bottom-y of 'top-left' = pad + text_h
    assert y == 8 + 40


def test_anchor_xy_free_uses_normalized_offset():
    pos = Position(anchor="free", offset_x=0.5, offset_y=0.5)
    x, y = anchor_xy(pos, text_w=100, text_h=40, pad=8, surface_w=1920, surface_h=1080)
    # center of 1920x1080 — text x = 1920/2 - 100/2 = 910, y = 1080/2 + 40/2 = 560
    assert x == 910
    assert y == 560


def test_draw_caption_returns_early_outside_window(qtbot):
    """fade_alpha == 0 케이스에서 painter 가 아무것도 그리지 않아도 예외 없이 반환."""
    from PySide6.QtGui import QImage, QPainter
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    try:
        # 시점 5000 은 in_ms~out_ms 범위 밖
        draw_caption(p, _caption(in_ms=0, out_ms=2000), position_ms=5000,
                     surface_w=100, surface_h=100)
    finally:
        p.end()
