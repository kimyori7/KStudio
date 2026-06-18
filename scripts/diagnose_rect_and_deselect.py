"""진단 — 화살표 선택/해제 + 사각형 효과를 PNG 로 렌더해 시각 확인.

생성 PNG (스크립트 옆 _diag_out/ 에):
- arrow_selected.png   : 화살표 선택 → 끝점 핸들 보임(꼭짓점 가림)
- arrow_deselected.png : 화살표 해제 → 핸들 사라지고 꼭짓점 드러남
- rect_outline.png     : 사각형 테두리만(중앙 투명)
- rect_selected.png    : 사각형 선택 → 네 모서리 핸들
- rect_faded.png       : 페이드 중간 — 더 옅게

QT_QPA_PLATFORM=offscreen 필요(자동 설정).
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.arrow import ArrowEffect, Point as APoint, Fade as AFade
from screen_recorder.effects.types.rect import RectEffect, Point as RPoint, Fade as RFade
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


W, H = 640, 360
OUT = Path(__file__).parent / "_diag_out"
OUT.mkdir(exist_ok=True)


def _bg() -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(40, 44, 52))   # 어두운 배경 (투명 핸들/선이 잘 보이게)
    return img


def _render(ov: PreviewOverlay, kind: str) -> QImage:
    img = _bg()
    ov.resize(W, H)
    ov._overlay_hits = []
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    for eff in ov._sidecar.effects:
        if eff.type != kind:
            continue
        if not (eff.in_ms <= ov._position_ms < eff.out_ms):
            continue
        if kind == "arrow":
            ov._draw_arrow_effect(p, eff)
        else:
            ov._draw_rect_effect(p, eff)
    p.end()
    return img


def main() -> None:
    app = QApplication.instance() or QApplication([])

    # --- 화살표 ---
    arrow = ArrowEffect(in_ms=0, out_ms=10_000,
                        start=APoint(x=0.25, y=0.55), end=APoint(x=0.78, y=0.4),
                        color="#ff4040", thickness=8, fade=AFade(in_ms=300, out_ms=300))
    ov = PreviewOverlay()
    ov.set_sidecar(Sidecar(source_path="x", source_hash="h",
                           trim=Trim(in_ms=0, out_ms=10_000), effects=[arrow]))
    ov.set_position_ms(5000)
    ov.set_selected_effect_id(arrow.id)
    _render(ov, "arrow").save(str(OUT / "arrow_selected.png"), "PNG")
    ov.set_selected_effect_id(None)
    _render(ov, "arrow").save(str(OUT / "arrow_deselected.png"), "PNG")

    # --- 사각형 ---
    rect = RectEffect(in_ms=0, out_ms=10_000,
                      start=RPoint(x=0.28, y=0.32), end=RPoint(x=0.72, y=0.68),
                      color="#ff4040", thickness=5, fade=RFade(in_ms=1000, out_ms=1000))
    ov2 = PreviewOverlay()
    ov2.set_sidecar(Sidecar(source_path="x", source_hash="h",
                            trim=Trim(in_ms=0, out_ms=10_000), effects=[rect]))
    ov2.set_position_ms(5000)
    _render(ov2, "rect").save(str(OUT / "rect_outline.png"), "PNG")
    ov2.set_selected_effect_id(rect.id)
    _render(ov2, "rect").save(str(OUT / "rect_selected.png"), "PNG")
    # 페이드 중간 (in 시작 0.5s → alpha 0.5).
    ov2.set_selected_effect_id(None)
    ov2.set_position_ms(500)
    _render(ov2, "rect").save(str(OUT / "rect_faded.png"), "PNG")

    print("saved to", OUT)


if __name__ == "__main__":
    main()
