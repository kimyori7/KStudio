"""speed_hud_png — SpeedEffect HUD 텍스트 ("▶▶ N× 배속") 를 투명 PNG 로 그려 export.

caption_png 와 같은 패턴 — overlay 입력으로 쓰임. player_widget._OutlinedLabel 의
시각 (흰 채움 + 검정 외곽선, bold 폰트) 을 재현.

크기는 텍스트가 들어갈 만큼 작게 잡고 (광 캔버스 PNG 아님), export_pipeline 에서
오른쪽 위 모서리 + 마진으로 overlay.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen,
)

from ..effects.types.speed import SpeedEffect


_HUD_PAD_PX = 6   # 텍스트 좌우/위아래 여백 (PNG 내부)


def _rate_label(rate: float) -> str:
    """배속 표시값. 정수면 "N", 소수면 trailing 0 제거.

    예: 2.0 → "2", 1.5 → "1.5", 10.0 → "10".
    """
    formatted = f"{float(rate):g}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def hud_text(rate: float) -> str:
    """player_widget.show_speed_hud 와 동일 포맷 (preview/export 일치)."""
    return f"▶▶  {_rate_label(rate)}× 배속"


def render_speed_hud_png(eff: SpeedEffect, *, font_pt: int, dst: Path) -> tuple[int, int]:
    """SpeedEffect 1 개의 HUD 를 투명 PNG 로 dst 에 저장. (w, h) 반환.

    font_pt 는 source 해상도 기준. preview 의 14pt 가 800px 너비 위젯에서
    적당한 비율이라면 source 1920 에선 1920/800 ≈ 2.4 배 = 34pt 정도가 비례적.
    호출자가 surface_w 기반으로 계산해 전달.
    """
    f = QFont()
    f.setBold(True)
    f.setPointSize(int(max(8, font_pt)))
    fm = QFontMetrics(f)
    text = hud_text(eff.rate)
    text_w = fm.horizontalAdvance(text)
    text_h = fm.height()
    w = text_w + 2 * _HUD_PAD_PX
    h = text_h + 2 * _HUD_PAD_PX
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)   # 완전 투명
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        path = QPainterPath()
        baseline_y = fm.ascent() + _HUD_PAD_PX
        path.addText(_HUD_PAD_PX, baseline_y, f, text)
        # 외곽선 — 굵은 검정.
        pen = QPen(QColor(0, 0, 0, 230))
        pen.setWidth(max(2, int(round(font_pt / 12))))   # font 비례 외곽 굵기
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # 채움 — 흰색.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(path)
    finally:
        p.end()
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dst), "PNG")
    return (w, h)
