"""rect_renderer — preview/PNG 공유 헬퍼 (테두리 사각형).

arrow_renderer 와 같은 패턴 — 같은 함수가 preview overlay 와 export PNG 둘 다
호출해 픽셀 일치 보장.

API:
- fade_alpha(rect, position_ms) -> float
- draw_rect(painter, rect, *, position_ms, surface_w, surface_h)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from ...effects.types.rect import RectEffect


def fade_alpha(r: RectEffect, position_ms: int) -> float:
    """페이드 인/아웃 알파 (0..1). arrow_renderer.fade_alpha 와 동일 공식."""
    t = position_ms - r.in_ms
    dur = r.out_ms - r.in_ms
    if dur <= 0 or t < 0 or t >= dur:
        return 0.0
    alpha = 1.0
    if r.fade.in_ms > 0 and t < r.fade.in_ms:
        alpha *= t / r.fade.in_ms
    time_to_end = dur - t
    if r.fade.out_ms > 0 and time_to_end < r.fade.out_ms:
        alpha *= time_to_end / r.fade.out_ms
    return max(0.0, min(1.0, alpha))


def draw_rect(p: QPainter, r: RectEffect, *, position_ms: int,
              surface_w: int, surface_h: int) -> None:
    """surface 안에 테두리 사각형 1개 그림. start/end 정규화 대각 모서리.

    두 점의 min/max 로 사각형을 만들어 모서리를 반대편 너머로 끌어도 비반전.
    테두리만(setBrush(NoBrush)) — 채움 없음.
    """
    if not (r.in_ms <= position_ms < r.out_ms):
        return
    alpha = fade_alpha(r, position_ms)
    if alpha <= 0:
        return
    # surface sanity 가드 (arrow_renderer 와 동일) — 비정상 값이면 paint 생략.
    if not (isinstance(surface_w, (int, float)) and isinstance(surface_h, (int, float))):
        return
    if not (surface_w > 0 and surface_h > 0):
        return
    if surface_w != surface_w or surface_h != surface_h:   # NaN
        return

    x0 = r.start.x * surface_w
    y0 = r.start.y * surface_h
    x1 = r.end.x * surface_w
    y1 = r.end.y * surface_h
    for v in (x0, y0, x1, y1):
        if v != v or v in (float("inf"), float("-inf")):
            return
    left = min(x0, x1)
    top = min(y0, y1)
    right = max(x0, x1)
    bottom = max(y0, y1)
    if right - left < 1 or bottom - top < 1:
        return

    color = QColor(r.color)
    color.setAlphaF(alpha)
    pen = QPen(color)
    pen.setWidth(r.thickness)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(left, top, right - left, bottom - top))
