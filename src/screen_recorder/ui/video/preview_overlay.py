"""영상 위에 효과 시뮬레이션을 그리는 투명 오버레이.

Stage 3a: 캡션만. Stage 4+ 에서 줌·SVG HUD 추가.

PlayerWidget 의 비디오 surface 위에 자식으로 떠 있다. 매 paint 마다 현재
재생 위치(_position_ms) 와 사이드카(_sidecar) 를 보고, in_ms~out_ms 안에
들어오는 캡션을 그린다. fade in/out 은 선형 알파 보간.

자유 위치 (anchor='free') 캡션은 마우스 드래그로 위치 조정. 그 외 영역의
마우스 이벤트는 하부 영상 surface 로 통과 (mousePressEvent 가 hit 안 되면
ignore() 호출).
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ...effects import Sidecar
from ...effects.types.caption import CaptionEffect, Position


class PreviewOverlay(QWidget):
    """투명 위젯 — paintEvent 에서 캡션을 그린다.

    free 모드 캡션은 클릭·드래그로 위치 조정. 그 외 영역의 마우스 이벤트는
    하부 영상 surface 로 ignore() 통과.
    """

    caption_position_changed = Signal(object)   # CaptionEffect — 드래그 후 새 position

    def __init__(self) -> None:
        super().__init__()
        # WA_TransparentForMouseEvents 를 끄고 hit-test 로 직접 처리해야 free 캡션
        # 드래그가 가능. 비-hit 영역은 mousePressEvent 에서 ignore() → 부모로 전달.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._sidecar: Optional[Sidecar] = None
        self._position_ms: int = 0
        # paintEvent 마다 free 캡션의 bounding box 저장 — mousePress hit-test 용.
        self._free_bboxes: dict[str, "QRect"] = {}
        # 드래그 상태
        self._drag_caption_id: Optional[str] = None
        self._drag_start_pos = None       # QPoint
        self._drag_orig_offset = (0.0, 0.0)
        self._drag_override_offset: Optional[tuple[float, float]] = None

    # ---------- public ----------
    def set_sidecar(self, sc: Optional[Sidecar]) -> None:
        self._sidecar = sc
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        self._free_bboxes = {}   # 매 paint 마다 갱신
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

        # 드래그 중이면 임시 override offset 으로 그림 (history push 안 됨, release 시점만 emit).
        position = c.position
        if c.id == self._drag_caption_id and self._drag_override_offset is not None:
            position = Position(anchor="free",
                                offset_x=self._drag_override_offset[0],
                                offset_y=self._drag_override_offset[1])

        # 위치
        pad = 8
        x, y = self._anchor_xy(position, text_w, text_h, pad)
        # 9-zone 모드의 offset 은 픽셀 단위 미세 조정. free 모드는 _anchor_xy 가 이미
        # offset_x/y(정규화 0~1) 로 절대 위치를 계산하므로 추가로 더하지 않는다.
        if position.anchor != "free":
            x += int(position.offset_x)
            y += int(position.offset_y)
        # free 모드 캡션의 hit-test 영역 (텍스트 + 약간의 padding) 저장.
        if position.anchor == "free":
            self._free_bboxes[c.id] = QRect(
                x - pad, y - text_h - pad,
                text_w + 2 * pad, text_h + 2 * pad,
            )

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

    # ---------- mouse (free 캡션 드래그) ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._sidecar is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        # 위에서 아래로 마지막 그려진 캡션이 가장 위에 있으니 역순 hit-test.
        for cid, bbox in reversed(list(self._free_bboxes.items())):
            if bbox.contains(pos):
                # 드래그 시작 — 원본 effect 의 offset 저장.
                for eff in self._sidecar.effects:
                    if eff.id == cid and eff.type == "caption":
                        self._drag_caption_id = cid
                        self._drag_start_pos = pos
                        self._drag_orig_offset = (eff.position.offset_x,
                                                  eff.position.offset_y)
                        self._drag_override_offset = self._drag_orig_offset
                        self.setCursor(Qt.ClosedHandCursor)
                        event.accept()
                        return
        # 캡션 hit 안 됨 → 하부 영상 surface 로 통과.
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_caption_id is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        delta_x = pos.x() - self._drag_start_pos.x()
        delta_y = pos.y() - self._drag_start_pos.y()
        w = max(1, self.width())
        h = max(1, self.height())
        new_x = max(0.0, min(1.0, self._drag_orig_offset[0] + delta_x / w))
        new_y = max(0.0, min(1.0, self._drag_orig_offset[1] + delta_y / h))
        self._drag_override_offset = (new_x, new_y)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_caption_id is None:
            event.ignore()
            return
        # release 시점 한 번만 시그널 emit → EditController 가 history push 1회.
        if self._sidecar is not None and self._drag_override_offset is not None:
            for eff in self._sidecar.effects:
                if eff.id == self._drag_caption_id and eff.type == "caption":
                    new_pos = Position(anchor="free",
                                       offset_x=self._drag_override_offset[0],
                                       offset_y=self._drag_override_offset[1])
                    new_eff = replace(eff, position=new_pos)
                    self.caption_position_changed.emit(new_eff)
                    break
        self._drag_caption_id = None
        self._drag_start_pos = None
        self._drag_override_offset = None
        self.unsetCursor()
        event.accept()

    def _anchor_xy(self, position, text_w: int, text_h: int, pad: int):
        """위젯 크기 기준 position → (text 베이스라인 좌표 x, y).

        - 9-zone anchor: 미리 정해진 9개 위치 중 하나 (offset 은 _draw_caption 이 픽셀 단위로 추가).
        - free anchor: offset_x/offset_y 가 정규화 좌표 (0=좌/상, 1=우/하). 텍스트 중심이
          (offset_x * w, offset_y * h) 가 되도록 베이스라인 위치 계산.
        """
        w, h = self.width(), self.height()
        anchor = position.anchor
        if anchor == "free":
            cx = position.offset_x * w
            cy = position.offset_y * h
            return (int(cx - text_w / 2), int(cy + text_h / 2))
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
