"""caption_png — 캡션 1개를 영상 해상도 투명 PNG 로 렌더.

ffmpeg overlay 필터의 입력으로 사용. 한 캡션의 모든 시각 효과 (페이드/외곽선/
그림자/배경) 가 sample_ms 시점의 알파 값으로 한 장에 담긴다.

페이드는 ffmpeg 의 fade=enable=between(t,...) 가 아닌, sample_ms 를 in_ms 와
out_ms 의 사이 적당한 시점으로 둬 그 시점의 alpha 한 장만 만든다 — 단순한 'static
PNG over time range' 합성이라 export_pipeline 에서 enable=between(t,in,out) 로
표시 구간만 제어. 페이드 자체는 별도 fade 필터 (alpha 채널 페이드) 로.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from ..effects.types.caption import CaptionEffect
from ..ui.video import caption_renderer


def render_caption_png(c: CaptionEffect, *,
                       surface_w: int, surface_h: int,
                       dst: Path, sample_ms: int | None = None) -> None:
    """캡션 1개를 영상 해상도 투명 PNG 로 그려 dst 에 저장.

    sample_ms 가 None 이면 (in_ms + out_ms) / 2 — 페이드 영향 없는 한가운데 시점
    (alpha = 1.0). 페이드는 export_pipeline 의 alpha fade 필터가 별도 처리.
    """
    if sample_ms is None:
        sample_ms = (c.in_ms + c.out_ms) // 2
    img = QImage(int(surface_w), int(surface_h), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)   # 완전 투명
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    try:
        caption_renderer.draw_caption(
            p, c, position_ms=sample_ms,
            surface_w=int(surface_w), surface_h=int(surface_h),
        )
    finally:
        p.end()
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dst), "PNG")
