"""caption_renderer — preview/PNG 공유 헬퍼.

PreviewOverlay 와 export 의 PNG 렌더 둘 다 호출. 같은 함수 사용 = 픽셀 일치.

API:
- fade_alpha(caption, position_ms) -> float  : 페이드 인/아웃 알파 (0..1)
- anchor_xy(position, text_w, text_h, pad, surface_w, surface_h) -> (x, y)
- draw_caption(painter, caption, position_ms, surface_w, surface_h) : 모든 효과 한 번에 그림
"""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from ...effects.types.caption import CaptionEffect, Position


def fade_alpha(c: CaptionEffect, position_ms: int) -> float:
    t = position_ms - c.in_ms
    dur = c.out_ms - c.in_ms
    if dur <= 0 or t < 0 or t >= dur:
        return 0.0
    a = 1.0
    if c.fade.in_ms > 0 and t < c.fade.in_ms:
        a *= t / c.fade.in_ms
    time_to_end = dur - t
    if c.fade.out_ms > 0 and time_to_end < c.fade.out_ms:
        a *= time_to_end / c.fade.out_ms
    return max(0.0, min(1.0, a))


def anchor_xy(position: Position, *, text_w: int, text_h: int, pad: int,
              surface_w: int, surface_h: int) -> tuple[int, int]:
    """anchor → text 베이스라인 좌표. free 면 정규화 (0~1) 좌표 사용."""
    if position.anchor == "free":
        cx = position.offset_x * surface_w
        cy = position.offset_y * surface_h
        return (int(cx - text_w / 2), int(cy + text_h / 2))
    rows = position.anchor.split("-")[0]
    cols = position.anchor.split("-")[1]
    if cols == "left":
        x = pad
    elif cols == "center":
        x = (surface_w - text_w) // 2
    else:
        x = surface_w - text_w - pad
    if rows == "top":
        y = pad + text_h
    elif rows == "middle":
        y = (surface_h + text_h) // 2
    else:
        y = surface_h - pad
    return (x, y)


def draw_caption(p: QPainter, c: CaptionEffect, *, position_ms: int,
                 surface_w: int, surface_h: int) -> None:
    """단일 캡션 1개를 surface 에 그린다 (페이드/외곽선/그림자/배경/본문 모두 처리)."""
    if not (c.in_ms <= position_ms < c.out_ms):
        return
    alpha = fade_alpha(c, position_ms)
    if alpha <= 0:
        return

    f = QFont(c.font.family, c.font.size)
    f.setBold(c.font.bold)
    p.setFont(f)
    fm = p.fontMetrics()
    text = c.text
    text_w = fm.horizontalAdvance(text) if text else 0
    text_h = fm.height()

    pad = 8
    x, y = anchor_xy(c.position, text_w=text_w, text_h=text_h, pad=pad,
                    surface_w=surface_w, surface_h=surface_h)
    if c.position.anchor != "free":
        x += int(c.position.offset_x)
        y += int(c.position.offset_y)

    # 배경 박스 — 텍스트 ascent/descent 기준 수직 균등 padding.
    # 이전: top 은 y-text_h (텍스트 꼭대기 = 정확히 0 pad), bottom 은 y+pad
    # (descent 포함 + pad) → 위는 padding 없고 아래만 있어 텍스트가 bg 의
    # 위쪽으로 치우쳐 "텍스트가 bg 살짝 아래에" 보이던 회귀.
    if c.background is not None:
        bg = QColor(c.background.color)
        bg.setAlphaF(c.background.opacity * alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        v_pad = pad // 2
        bg_top = y - fm.ascent() - v_pad
        bg_h = fm.ascent() + fm.descent() + 2 * v_pad
        p.drawRoundedRect(x - pad, bg_top, text_w + 2 * pad, bg_h, 4, 4)

    # 외곽선
    if c.stroke is not None and c.stroke.width > 0:
        stroke = QColor(c.stroke.color)
        stroke.setAlphaF(alpha)
        pen = QPen(stroke)
        pen.setWidth(c.stroke.width)
        p.setPen(pen)
        p.drawText(x, y, text)

    # 그림자
    if c.shadow:
        sh = QColor(0, 0, 0)
        sh.setAlphaF(0.6 * alpha)
        p.setPen(sh)
        p.drawText(x + 2, y + 2, text)

    # 본 텍스트
    fill = QColor(c.fill)
    fill.setAlphaF(alpha)
    p.setPen(fill)
    p.drawText(x, y, text)
