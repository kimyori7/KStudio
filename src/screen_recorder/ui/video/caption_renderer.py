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
    """단일 캡션 1개를 surface 에 그린다 (페이드/외곽선/그림자/배경/본문 모두 처리).

    text 안의 줄바꿈(\\n) 은 multi-line 으로 렌더. 인스펙터에서 Enter 로 줄 넘긴
    것이 실제 렌더에도 반영된다 (이전: drawText 가 \\n 을 무시해 한 줄로 보임).
    """
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
    lines = text.split("\n") if text else [""]
    line_h = fm.height()
    line_widths = [fm.horizontalAdvance(line) for line in lines]
    text_w = max(line_widths) if line_widths else 0
    text_h = line_h * len(lines)

    pad = 8
    # anchor_xy 는 단일 baseline 을 가정한 좌표 (text_h 가 한 줄 높이일 때).
    # multi-line 에서는 첫 줄의 baseline 위치를 다시 계산한다.
    x, y = anchor_xy(c.position, text_w=text_w, text_h=text_h, pad=pad,
                    surface_w=surface_w, surface_h=surface_h)
    # 9-zone anchor 의 픽셀 offset 적용은 surface 크기 변경 (창 ↔ 풀스크린) 시
    # 캡션 위치가 어긋나던 회귀 원인 — 픽셀 절대값이라 surface 가 커지면 상대
    # 위치 달라짐. free anchor 만 정규화 offset_x/offset_y 사용 — 거기서만 적용.
    # 9-zone 미세 조정이 필요하면 사용자가 free anchor 로 전환해 정규화 좌표 사용.
    if c.position.anchor == "free":
        # anchor_xy 가 이미 정규화 좌표를 적용한 좌표를 반환 — 추가 offset 불필요.
        pass

    # 첫 줄 baseline. y 가 마지막 줄 baseline 이라 가정하면 첫 줄 = y - (n-1)*line_h.
    first_baseline_y = y - (len(lines) - 1) * line_h

    # 배경 박스 — 전체 multi-line bbox 를 감쌈.
    if c.background is not None:
        bg = QColor(c.background.color)
        bg.setAlphaF(c.background.opacity * alpha)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        v_pad = pad // 2
        bg_top = first_baseline_y - fm.ascent() - v_pad
        bg_h = (len(lines) - 1) * line_h + fm.ascent() + fm.descent() + 2 * v_pad
        p.drawRoundedRect(x - pad, bg_top, text_w + 2 * pad, bg_h, 4, 4)

    def _draw_line(line_idx: int, line: str, dx: int = 0, dy: int = 0) -> None:
        """line 별 baseline 위치 + 가로 정렬. text_align 이 우선, 없으면 anchor 따라.

        text_align 은 캡션 박스 *내부* 의 줄 정렬. position.anchor 는 캡션
        박스 *전체* 위치. 둘은 직교 — 예: 캡션 박스를 화면 우측 하단에 배치
        (anchor=bottom-right) 하면서 박스 안 텍스트는 왼쪽 정렬 (text_align=left).
        """
        ly = first_baseline_y + line_idx * line_h + dy
        align = getattr(c, "text_align", "center")
        if align == "center":
            line_x = x + (text_w - line_widths[line_idx]) // 2 + dx
        elif align == "right":
            line_x = x + (text_w - line_widths[line_idx]) + dx
        else:   # left
            line_x = x + dx
        p.drawText(line_x, ly, line)

    # 외곽선
    if c.stroke is not None and c.stroke.width > 0:
        stroke = QColor(c.stroke.color)
        stroke.setAlphaF(alpha)
        pen = QPen(stroke)
        pen.setWidth(c.stroke.width)
        p.setPen(pen)
        for i, line in enumerate(lines):
            _draw_line(i, line)

    # 그림자
    if c.shadow:
        sh = QColor(0, 0, 0)
        sh.setAlphaF(0.6 * alpha)
        p.setPen(sh)
        for i, line in enumerate(lines):
            _draw_line(i, line, dx=2, dy=2)

    # 본 텍스트
    fill = QColor(c.fill)
    fill.setAlphaF(alpha)
    p.setPen(fill)
    for i, line in enumerate(lines):
        _draw_line(i, line)
