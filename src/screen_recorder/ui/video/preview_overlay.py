"""영상 위에 효과 시뮬레이션을 그리는 투명 오버레이.

Stage 3a: 캡션만. Stage 4+ 에서 줌·SVG HUD 추가.

PlayerWidget 의 비디오 surface 위에 자식으로 떠 있다. 매 paint 마다 현재
재생 위치(_position_ms) 와 사이드카(_sidecar) 를 보고, in_ms~out_ms 안에
들어오는 캡션을 그린다. fade in/out 은 선형 알파 보간.

캡션 드래그: 어느 anchor 든 화면에서 드래그 가능. 드래그 시 자동으로
anchor='free' 로 전환되고 정규화 좌표(0~1) 로 저장. 호버 시 손 모양 커서로
드래그 가능함을 시각화. 그 외 영역의 마우스 이벤트는 하부 영상 surface 로
통과 (mousePressEvent 가 hit 안 되면 ignore() 호출).
"""
from __future__ import annotations
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from ...effects import Sidecar
from ...effects.types.caption import CaptionEffect, Position
from . import caption_renderer


class PreviewOverlay(QWidget):
    """투명 위젯 — paintEvent 에서 캡션을 그린다.

    어느 anchor 든 캡션은 화면 위에서 드래그 가능. 드래그 시작 시 자동으로
    anchor='free' 로 전환됨. 캡션 외 영역의 마우스 이벤트는 ignore() 통과.
    """

    caption_position_changed = Signal(object)   # CaptionEffect — 드래그 후 새 position

    def __init__(self) -> None:
        super().__init__()
        # WA_TransparentForMouseEvents 를 끄고 hit-test 로 직접 처리해야 캡션
        # 드래그가 가능. 비-hit 영역은 mousePressEvent 에서 ignore() → 부모로 전달.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 호버 커서 변경 위해 mouseTracking ON.
        self.setMouseTracking(True)
        self._sidecar: Optional[Sidecar] = None
        self._position_ms: int = 0
        # paintEvent 마다 모든 캡션의 bounding box 저장 — mousePress/Move hit-test 용.
        self._caption_bboxes: dict[str, "QRect"] = {}
        # 드래그 상태
        self._drag_caption_id: Optional[str] = None
        self._drag_start_pos = None       # QPoint
        self._drag_start_offset_norm: tuple[float, float] = (0.5, 0.5)
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
        self._caption_bboxes = {}   # 매 paint 마다 갱신
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
        # 드래그 중인 경우 임시 override position 사용
        position = c.position
        if c.id == self._drag_caption_id and self._drag_override_offset is not None:
            position = Position(anchor="free",
                                offset_x=self._drag_override_offset[0],
                                offset_y=self._drag_override_offset[1])
        # caption_renderer 의 모든 그리기를 호출하기 전에 hit-test bbox 를 기록.
        # 텍스트 width 계산을 위해 폰트는 잠시 set 후 fontMetrics 만 사용.
        f = QFont(c.font.family, c.font.size)
        f.setBold(c.font.bold)
        p.setFont(f)
        fm = p.fontMetrics()
        text_w = fm.horizontalAdvance(c.text) if c.text else 0
        text_h = fm.height()
        pad = 8
        x, y = caption_renderer.anchor_xy(
            position, text_w=text_w, text_h=text_h, pad=pad,
            surface_w=self.width(), surface_h=self.height(),
        )
        if position.anchor != "free":
            x += int(position.offset_x)
            y += int(position.offset_y)
        # 모든 anchor 의 캡션을 hit-test 대상으로 등록 — 호버/드래그 가능.
        # 보이는 (in_ms~out_ms 범위 내) 캡션만 등록해 안 보이는 캡션 클릭 방지.
        if c.in_ms <= self._position_ms < c.out_ms:
            self._caption_bboxes[c.id] = QRect(
                x - pad, y - text_h - pad, text_w + 2 * pad, text_h + 2 * pad,
            )
        # 실제 그리기는 (override 적용된) effect 인스턴스로 caption_renderer 호출.
        eff_for_draw = replace(c, position=position) if position is not c.position else c
        caption_renderer.draw_caption(
            p, eff_for_draw, position_ms=self._position_ms,
            surface_w=self.width(), surface_h=self.height(),
        )

    # ---------- mouse (캡션 드래그 — anchor 무관, 자동으로 free 전환) ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or self._sidecar is None:
            event.ignore()
            return
        pos = event.position().toPoint()
        # 위에서 아래로 마지막 그려진 캡션이 가장 위에 있으니 역순 hit-test.
        for cid, bbox in reversed(list(self._caption_bboxes.items())):
            if bbox.contains(pos):
                # 드래그 시작 — 캡션 hit. anchor 무관: bbox 중심을 정규화 좌표 시작점으로 사용
                # → 어느 anchor 든 자연스럽게 free 로 전환된다.
                self._drag_caption_id = cid
                self._drag_start_pos = pos
                w = max(1, self.width())
                h = max(1, self.height())
                cx = (bbox.left() + bbox.right()) / 2.0
                cy = (bbox.top() + bbox.bottom()) / 2.0
                self._drag_start_offset_norm = (cx / w, cy / h)
                self._drag_override_offset = self._drag_start_offset_norm
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
        # 캡션 hit 안 됨 → 하부 영상 surface 로 통과.
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._drag_caption_id is None:
            # 드래그 중 아니면 호버: 캡션 위면 OpenHand, 아니면 기본.
            for bbox in self._caption_bboxes.values():
                if bbox.contains(pos):
                    self.setCursor(Qt.OpenHandCursor)
                    event.accept()
                    return
            self.unsetCursor()
            event.ignore()
            return
        delta_x = pos.x() - self._drag_start_pos.x()
        delta_y = pos.y() - self._drag_start_pos.y()
        w = max(1, self.width())
        h = max(1, self.height())
        new_x = max(0.0, min(1.0, self._drag_start_offset_norm[0] + delta_x / w))
        new_y = max(0.0, min(1.0, self._drag_start_offset_norm[1] + delta_y / h))
        self._drag_override_offset = (new_x, new_y)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_caption_id is None:
            event.ignore()
            return
        # release 시점 한 번만 시그널 emit → EditController 가 history push 1회.
        # 어느 anchor 였든 free 로 전환됨.
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

