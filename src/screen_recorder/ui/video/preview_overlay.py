"""영상 위에 효과 시뮬레이션을 그리는 투명 오버레이.

Stage 3a: 캡션만. Stage 4+ 에서 줌·SVG HUD 추가.

PlayerWidget 의 비디오 surface 위에 자식으로 떠 있다. 매 paint 마다 현재
재생 위치(_position_ms) 와 사이드카(_sidecar) 를 보고, in_ms~out_ms 안에
들어오는 캡션을 그린다. fade in/out 은 선형 알파 보간.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ...effects import Sidecar
from ...effects.types.caption import CaptionEffect


class PreviewOverlay(QWidget):
    """투명 위젯 — paintEvent 에서 캡션을 그린다.

    하부 영상 surface 의 paint 결과 위에 그려야 하므로 WA_TransparentForMouseEvents
    + WA_NoSystemBackground 로 마우스·배경 모두 통과시킨다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._sidecar: Optional[Sidecar] = None
        self._position_ms: int = 0

    # ---------- public ----------
    def set_sidecar(self, sc: Optional[Sidecar]) -> None:
        self._sidecar = sc
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        if self._sidecar is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        for eff in self._sidecar.effects:
            if eff.type != "caption":
                continue
            self._draw_caption(p, eff)

    def _draw_caption(self, p: QPainter, c: CaptionEffect) -> None:
        if not (c.in_ms <= self._position_ms < c.out_ms):
            return
        alpha = self._fade_alpha(c)
        if alpha <= 0:
            return
        # 폰트
        f = QFont(c.font.family, c.font.size)
        f.setBold(c.font.bold)
        p.setFont(f)
        fm = p.fontMetrics()
        text = c.text
        text_w = fm.horizontalAdvance(text) if text else 0
        text_h = fm.height()

        # 위치
        pad = 8
        x, y = self._anchor_xy(c.position.anchor, text_w, text_h, pad)
        x += int(c.position.offset_x)
        y += int(c.position.offset_y)

        # 배경 박스
        if c.background is not None:
            bg = QColor(c.background.color)
            bg.setAlphaF(c.background.opacity * alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(x - pad, y - text_h, text_w + 2 * pad, text_h + pad, 4, 4)

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

    def _fade_alpha(self, c: CaptionEffect) -> float:
        """fade in/out 을 고려한 알파 (0..1)."""
        t = self._position_ms - c.in_ms
        dur = c.out_ms - c.in_ms
        if t < 0 or t >= dur:
            return 0.0
        a = 1.0
        if c.fade.in_ms > 0 and t < c.fade.in_ms:
            a *= t / c.fade.in_ms
        time_to_end = dur - t
        if c.fade.out_ms > 0 and time_to_end < c.fade.out_ms:
            a *= time_to_end / c.fade.out_ms
        return max(0.0, min(1.0, a))

    def _anchor_xy(self, anchor: str, text_w: int, text_h: int, pad: int):
        """위젯 크기 기준 anchor → (text 베이스라인 좌표 x, y)."""
        w, h = self.width(), self.height()
        # 9-zone (free 는 middle-center 처럼 처리하고 offset_x/offset_y 가 정규화 좌표)
        if anchor == "free":
            return (int(w * 0.5 - text_w / 2), int(h * 0.5 + text_h / 2))
        rows = anchor.split("-")[0]   # top/middle/bottom
        cols = anchor.split("-")[1]   # left/center/right
        if cols == "left":
            x = pad
        elif cols == "center":
            x = (w - text_w) // 2
        else:
            x = w - text_w - pad
        if rows == "top":
            y = pad + text_h
        elif rows == "middle":
            y = (h + text_h) // 2
        else:  # bottom
            y = h - pad
        return (x, y)
