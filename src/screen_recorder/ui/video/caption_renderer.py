"""caption_renderer — preview/PNG 공유 헬퍼.

PreviewOverlay 와 export 의 PNG 렌더 둘 다 호출. 같은 함수 사용 = 픽셀 일치.

API:
- fade_alpha(caption, position_ms) -> float  : 페이드 인/아웃 알파 (0..1)
- anchor_xy(position, text_w, text_h, pad, surface_w, surface_h) -> (x, y)
- draw_caption(painter, caption, position_ms, surface_w, surface_h) : 모든 효과 한 번에 그림
- clamp_free_offset(text_w, text_h, surface_w, surface_h, offset_x, offset_y) -> (x, y)
    : free anchor 의 정규화 (0~1) 중심점을 텍스트 bbox 가 surface 안에 머물도록 잘라낸다.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)

from ...effects.types.caption import CaptionEffect, Position


def measure_text(c: CaptionEffect) -> tuple[int, int]:
    """캡션 텍스트의 (width, height) 픽셀. multi-line 고려."""
    f = QFont(c.font.family, c.font.size)
    f.setBold(c.font.bold)
    fm = QFontMetrics(f)
    text = c.text or ""
    lines = text.split("\n") if text else [""]
    line_h = fm.height()
    widths = [fm.horizontalAdvance(line) for line in lines]
    return (max(widths) if widths else 0, line_h * len(lines))


def clamp_free_offset(
    text_w: int, text_h: int,
    surface_w: int, surface_h: int,
    offset_x: float, offset_y: float,
    pad: int = 8,
) -> tuple[float, float]:
    """free anchor 의 (offset_x, offset_y) 정규화 중심점을 surface 안에 머물게 클램프.

    drag 가 anchor 좌표만 [0, 1] 클램프하면 텍스트 절반이 화면 밖으로 빠짐 — free 는
    anchor 가 텍스트 *중심* 이라서. (text_w/(2*surface_w), 1 - text_w/(2*surface_w)) 로
    half-width margin 만큼 더 안쪽으로 잘라낸다. pad 도 함께 고려.

    텍스트가 surface 보다 큰 (드물지만) 경우엔 0.5 로 고정 — 어느 방향으로 잡아도
    bbox 가 안 들어맞으므로 가운데에 두는 게 사용자 의도에 가장 가까움.
    """
    sw = max(1, surface_w)
    sh = max(1, surface_h)
    half_w_n = (text_w / 2.0 + pad) / sw
    half_h_n = (text_h / 2.0 + pad) / sh
    if half_w_n >= 0.5:
        ox = 0.5
    else:
        ox = max(half_w_n, min(1.0 - half_w_n, float(offset_x)))
    if half_h_n >= 0.5:
        oy = 0.5
    else:
        oy = max(half_h_n, min(1.0 - half_h_n, float(offset_y)))
    return (ox, oy)


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
    """anchor → text 베이스라인 좌표. free 면 정규화 (0~1) 좌표 사용.

    반환 좌표 (x, y) 는 첫 줄 baseline 의 (왼쪽, 아래) — text bbox 가 surface 안에
    머물도록 안전 클램프. 9-zone / free 모두 동일 적용:
    - x ∈ [pad, surface_w - text_w - pad]
    - y ∈ [pad + text_h, surface_h - pad]
    텍스트가 surface 보다 크면 (pad, pad + text_h) 로 좌상단 정렬 (덜 어색).
    """
    if position.anchor == "free":
        cx = position.offset_x * surface_w
        cy = position.offset_y * surface_h
        x = int(cx - text_w / 2)
        y = int(cy + text_h / 2)
    else:
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
    # bbox 안전 클램프 — 사용자가 어떤 경로로 (드래그 / 인스펙터 / 옛 사이드카) 값을
    # 넣어도 캡션이 화면 밖으로 빠지지 않도록.
    max_x = surface_w - text_w - pad
    min_y = pad + text_h
    max_y = surface_h - pad
    if max_x < pad:
        x = pad
    else:
        x = max(pad, min(max_x, x))
    if max_y < min_y:
        y = min_y
    else:
        y = max(min_y, min(max_y, y))
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
    # path fill 은 drawText 보다 glyph 영역이 빽빽 → fm.height() 만으로는 멀티라인 사이
    # 시각적 간격이 거의 0. typography 표준 1.2× 적용 (lineSpacing 보다 살짝 더 여유).
    line_h = max(fm.height(), int(round(fm.height() * 1.2)))
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

    def _line_x(line_idx: int) -> int:
        """line 별 가로 시작 좌표. text_align 이 캡션 박스 *내부* 의 줄 정렬."""
        align = getattr(c, "text_align", "center")
        if align == "center":
            return x + (text_w - line_widths[line_idx]) // 2
        if align == "right":
            return x + (text_w - line_widths[line_idx])
        return x   # left

    # 외곽선 / 그림자 / 본문 — QPainterPath 로 합쳐서 그림.
    # QPainter.drawText 는 QPen 의 width 를 무시 (텍스트 outline 두께가 적용 안 됨).
    # path.addText 후 strokePath 로 그리면 실제 두께가 반영. shadow 도 같은 path 를
    # offset 으로 fill 해 그림자 효과.
    full_path = QPainterPath()
    for i, line in enumerate(lines):
        if not line:
            continue
        ly = first_baseline_y + i * line_h
        full_path.addText(QPointF(_line_x(i), ly), f, line)

    # 그림자 — 본 텍스트보다 먼저 그려야 본문이 위에 오면서 우하단 그림자가 보임.
    # offset 은 font size 비례 (font 가 크면 그림자도 커야 자연스러움).
    if c.shadow:
        offset = max(2, int(round(c.font.size * 0.08)))
        sh = QColor(0, 0, 0)
        sh.setAlphaF(0.55 * alpha)
        p.save()
        p.translate(offset, offset)
        p.setPen(Qt.NoPen)
        p.setBrush(sh)
        p.drawPath(full_path)
        p.restore()

    # 외곽선 — width 를 두 배로 그린 뒤 본문이 가운데를 덮는 패턴 (Qt 의 strokePath 는
    # 중심선 기준 양쪽으로 width/2 씩 — 본문 fill 이 안쪽 절반을 덮으므로 시각상 두께가
    # 정확히 stroke.width 가 됨).
    if c.stroke is not None and c.stroke.width > 0:
        stroke_col = QColor(c.stroke.color)
        stroke_col.setAlphaF(alpha)
        pen = QPen(stroke_col)
        pen.setWidthF(float(c.stroke.width) * 2.0)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.strokePath(full_path, pen)

    # 본 텍스트
    fill = QColor(c.fill)
    fill.setAlphaF(alpha)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(fill))
    p.drawPath(full_path)
