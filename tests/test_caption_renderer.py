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


def _leftmost_red_x_per_y(img, h):
    """y 별 가장 왼쪽 빨강 픽셀의 x 반환 ({} 가 비어있으면 빨강 없는 줄)."""
    from PySide6.QtGui import QColor
    out: dict[int, int] = {}
    for y in range(0, h):
        for x in range(0, img.width()):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.red() > 200 and c.green() < 80 and c.blue() < 80:
                out[y] = x
                break
    return out


def test_text_align_left_vs_center_short_line_shifts_left(qtbot):
    """동일 캡션을 align=left 와 align=center 로 렌더 → 짧은 줄의 leftmost x 가
    left 가 center 보다 작거나 같아야 (좌측으로 이동)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    def render(align):
        cap = CaptionEffect(
            in_ms=0, out_ms=10_000, text="long-text-here\nA",
            fill="#ff0000", fade=Fade(in_ms=0, out_ms=0),
            position=Position(anchor="middle-center"),
            text_align=align,
        )
        img = QImage(600, 200, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        draw_caption(p, cap, position_ms=1000, surface_w=600, surface_h=200)
        p.end()
        return img

    img_left = render("left")
    img_center = render("center")
    lmx_left = _leftmost_red_x_per_y(img_left, 200)
    lmx_center = _leftmost_red_x_per_y(img_center, 200)
    # 둘 다 픽셀 존재.
    assert lmx_left and lmx_center
    # 가장 좁은 줄 ("A") 의 leftmost x — left 가 center 보다 작거나 같음 (대등 케이스 허용).
    short_left = min(lmx_left.values())
    short_center = min(lmx_center.values())
    assert short_left <= short_center, (
        f"left-aligned short line x={short_left} should be ≤ center-aligned x={short_center}"
    )


def test_text_align_right_vs_center_short_line_shifts_right(qtbot):
    """동일 캡션을 align=right 와 align=center → 짧은 줄의 leftmost x 가 right 가 center 보다 큼."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    def render(align):
        cap = CaptionEffect(
            in_ms=0, out_ms=10_000, text="long-text-here\nA",
            fill="#ff0000", fade=Fade(in_ms=0, out_ms=0),
            position=Position(anchor="middle-center"),
            text_align=align,
        )
        img = QImage(600, 200, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        draw_caption(p, cap, position_ms=1000, surface_w=600, surface_h=200)
        p.end()
        return img

    img_right = render("right")
    img_center = render("center")
    lmx_right = _leftmost_red_x_per_y(img_right, 200)
    lmx_center = _leftmost_red_x_per_y(img_center, 200)
    short_right = max(lmx_right.values())   # 짧은 줄 = leftmost 가 가장 큰 y 의 x
    short_center = max(lmx_center.values())
    assert short_right >= short_center, (
        f"right-aligned short line x={short_right} should be ≥ center-aligned x={short_center}"
    )


def test_draw_caption_multiline_renders_each_line(qtbot):
    """text 안의 \\n 이 multi-line 으로 렌더 — 회귀: drawText 가 \\n 무시해서 한 줄.

    fill 색 (빨강) 픽셀이 두 별개의 y 영역에서 검출되면 줄바꿈이 적용된 것.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    cap = CaptionEffect(
        in_ms=0, out_ms=10_000, text="hello\nworld",
        fill="#ff0000", fade=Fade(in_ms=0, out_ms=0),
        position=Position(anchor="middle-center"),
    )
    img = QImage(400, 200, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_caption(p, cap, position_ms=1000, surface_w=400, surface_h=200)
    p.end()

    # y 별 빨강 픽셀 존재 여부 그래프 — 빨강이 있는 y 구간이 2 그룹.
    red_ys = []
    for y in range(0, 200, 2):
        for x in range(0, 400, 4):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.red() > 200 and c.green() < 80 and c.blue() < 80 and c.alpha() > 50:
                red_ys.append(y)
                break
    # red_ys 가 연속된 2 그룹이어야 (line1 / gap / line2).
    if not red_ys:
        raise AssertionError("no red pixels rendered")
    gaps = [b - a for a, b in zip(red_ys, red_ys[1:]) if b - a > 6]
    assert gaps, f"only one line of red pixels detected — \\n not honored. ys={red_ys[:5]}..{red_ys[-5:]}"


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
