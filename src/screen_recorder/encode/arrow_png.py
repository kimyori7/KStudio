"""arrow_png — ArrowEffect 1개를 영상 해상도 투명 PNG 로 렌더 (caption_png 와 동일 패턴)."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtGui import QImage, QPainter

from ..effects.types.arrow import ArrowEffect
from ..ui.video import arrow_renderer


def render_arrow_png(a: ArrowEffect, *,
                     surface_w: int, surface_h: int,
                     dst: Path, sample_ms: int | None = None) -> None:
    """ArrowEffect 1개를 surface 크기 투명 PNG 로 dst 에 저장.

    sample_ms 가 None 이면 (in_ms+out_ms)/2 — 페이드 영향 없는 한가운데 시점.
    페이드는 export_pipeline 의 alpha fade 필터가 별도 처리.
    """
    if sample_ms is None:
        sample_ms = (a.in_ms + a.out_ms) // 2
    img = QImage(int(surface_w), int(surface_h), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    try:
        arrow_renderer.draw_arrow(
            p, a, position_ms=sample_ms,
            surface_w=int(surface_w), surface_h=int(surface_h),
        )
    finally:
        p.end()
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dst), "PNG")
