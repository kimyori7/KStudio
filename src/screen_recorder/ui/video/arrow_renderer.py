"""arrow_renderer — preview/PNG 공유 헬퍼.

caption_renderer 와 같은 패턴 — 같은 함수가 preview overlay 와 export PNG 둘 다
호출. 픽셀 일치 보장.

API:
- fade_alpha(arrow, position_ms) -> float
- draw_arrow(painter, arrow, *, position_ms, surface_w, surface_h)
"""
from __future__ import annotations
import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from ...effects.types.arrow import ArrowEffect


def fade_alpha(a: ArrowEffect, position_ms: int) -> float:
    """페이드 인/아웃 알파 (0..1). caption_renderer.fade_alpha 와 동일 공식."""
    t = position_ms - a.in_ms
    dur = a.out_ms - a.in_ms
    if dur <= 0 or t < 0 or t >= dur:
        return 0.0
    alpha = 1.0
    if a.fade.in_ms > 0 and t < a.fade.in_ms:
        alpha *= t / a.fade.in_ms
    time_to_end = dur - t
    if a.fade.out_ms > 0 and time_to_end < a.fade.out_ms:
        alpha *= time_to_end / a.fade.out_ms
    return max(0.0, min(1.0, alpha))


def draw_arrow(p: QPainter, a: ArrowEffect, *, position_ms: int,
               surface_w: int, surface_h: int) -> None:
    """surface 안에 화살표 1개 그림. start/end 정규화 좌표, thickness 는 source px.

    arrowhead 는 end 쪽 — 길이/너비는 thickness 비례 (자연스러운 비율 유지).
    """
    if not (a.in_ms <= position_ms < a.out_ms):
        return
    alpha = fade_alpha(a, position_ms)
    if alpha <= 0:
        return
    # 2026-05-13 진단 가드 — surface 가 비정상(0/NaN/거대값)이면 paint 자체를 건너뜀.
    # 사용자 보고 "화살표 있는 구간에 들어가니 멈춤" — paint 폭주/NaN 가능성 차단.
    if not (isinstance(surface_w, (int, float)) and isinstance(surface_h, (int, float))):
        return
    if not (surface_w > 0 and surface_h > 0):
        return
    if surface_w != surface_w or surface_h != surface_h:   # NaN check
        return
    sx = a.start.x * surface_w
    sy = a.start.y * surface_h
    ex = a.end.x * surface_w
    ey = a.end.y * surface_h
    dx = ex - sx
    dy = ey - sy
    length = math.hypot(dx, dy)
    if length < 1:
        return
    # 좌표 sanity — NaN/Inf 면 Qt 가 paint queue 에서 무한 처리 가능.
    for v in (sx, sy, ex, ey, length):
        if v != v or v in (float("inf"), float("-inf")):
            return
    ux = dx / length
    uy = dy / length

    color = QColor(a.color)
    color.setAlphaF(alpha)

    # arrowhead 길이 = thickness × 3, 너비 = thickness × 1.4 — head_scale 로 같이 키움.
    # head_scale 기본 1.0 = 기존 동작. 굵기와 독립이라 얇은 선에 큰 머리도 가능.
    head_scale = getattr(a, "head_scale", 1.0)
    head_len = a.thickness * 3 * head_scale
    head_half_w = a.thickness * 1.4 * head_scale
    # 본체 끝점 = end - head_len * 방향 (head 가 본체에 매끄럽게 이어지도록).
    bx = ex - ux * head_len
    by = ey - uy * head_len

    # 1) 본체 선 — Round cap 으로 부드러운 끝.
    pen = QPen(color)
    pen.setWidth(a.thickness)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(sx, sy), QPointF(bx, by))

    # 2) arrowhead — 채워진 삼각형. 두 base 점은 (bx, by) 에서 수직 방향으로 head_half_w.
    nx = -uy   # 수직 (좌)
    ny = ux
    head = QPolygonF([
        QPointF(ex, ey),
        QPointF(bx + nx * head_half_w, by + ny * head_half_w),
        QPointF(bx - nx * head_half_w, by - ny * head_half_w),
    ])
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPolygon(head)
