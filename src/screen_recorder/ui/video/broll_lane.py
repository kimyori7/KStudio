"""BrollLane — broll(곁들임 영상) 효과의 lane 자식 클래스.

ZoomLane 패턴 답습 — 막대 그리기 + 🎞 파일명 라벨 + 좌클릭 선택 +
좌우 드래그(시간 이동) + 양 끝 드래그(길이 조정) + Delete 키 삭제.

paint 색은 _TYPE_COLOR["broll"] 의 주황 계열 + 알파 (effect_lanes_widget._TYPE_COLOR
와 일관 — 헤더 색과 막대 색이 시각적으로 매칭).

v1: PiP only — 라벨은 src 의 basename. 비어있으면 '?'.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen,
)

from ...effects.types.broll import BrollEffect
from .effect_lane import EffectLane


_HEADER_WIDTH = 56
_BAR_RADIUS = 3
_EDGE_HANDLE_PX = 5
# effect_lanes_widget._TYPE_COLOR["broll"] = "#f59e0b" (주황). RGB(245, 158, 11).
_BAR_BG = QColor(245, 158, 11, 180)
_BAR_BG_SELECTED = QColor(251, 191, 36, 230)
_BAR_BORDER = QColor(0, 0, 0, 220)
_BAR_BORDER_SELECTED = QColor(255, 255, 255, 230)
_TEXT_COLOR = QColor(255, 255, 255, 235)


class BrollLane(EffectLane):
    """곁들임 영상 효과 lane — 막대 그리기·드래그·삭제."""

    def __init__(self, effect_type: str, header_label: str, color: str) -> None:
        super().__init__(effect_type, header_label, color)
        self.setFocusPolicy(Qt.StrongFocus)
        self._selected_id: Optional[str] = None
        self._drag_id: Optional[str] = None
        self._drag_kind: Optional[str] = None
        self._drag_start_x: int = 0
        self._drag_orig_in: int = 0
        self._drag_orig_out: int = 0
        self._drag_last_eff = None

    # ---------- public ----------
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    # ---------- helpers ----------
    def _bar_rect_for(self, eff: BrollEffect):
        return self._ms_to_x(eff.in_ms), self._ms_to_x(eff.out_ms)

    def _hit_test(self, x: int, y: int | None = None):
        if x < _HEADER_WIDTH:
            return None, None
        for eff in self._effects:
            x1, x2 = self._bar_rect_for(eff)
            if not (x1 <= x <= x2):
                continue
            if y is not None:
                ti = int(getattr(eff, "track_idx", 0))
                row_top = self._row_y_top(ti)
                if not (row_top <= y < row_top + self.TRACK_ROW_HEIGHT):
                    continue
            if x - x1 <= _EDGE_HANDLE_PX:
                return eff, "left"
            if x2 - x <= _EDGE_HANDLE_PX:
                return eff, "right"
            return eff, "move"
        return None, None

    @staticmethod
    def _label_for(eff: BrollEffect) -> str:
        """막대 안에 표시할 라벨 — 🎞 파일명 (또는 '?')."""
        basename = Path(eff.src).name if eff.src else ""
        return f"🎞 {basename or '?'}"

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._duration_ms <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for eff in self._effects:
            x1, x2 = self._bar_rect_for(eff)
            if x2 <= x1:
                continue
            ti = int(getattr(eff, "track_idx", 0))
            row_top = self._row_y_top(ti)
            selected = (eff.id == self._selected_id)
            p.setBrush(_BAR_BG_SELECTED if selected else _BAR_BG)
            pen = QPen(_BAR_BORDER_SELECTED if selected else _BAR_BORDER)
            pen.setWidth(2 if selected else 1)
            p.setPen(pen)
            p.drawRoundedRect(x1, row_top + 2, x2 - x1, self.TRACK_ROW_HEIGHT - 4,
                              _BAR_RADIUS, _BAR_RADIUS)
            if x2 - x1 > 24:
                p.setPen(_TEXT_COLOR)
                p.drawText(x1 + 4, row_top, x2 - x1 - 8, self.TRACK_ROW_HEIGHT,
                           Qt.AlignVCenter | Qt.AlignLeft, self._label_for(eff))

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        y = int(event.position().y())
        if event.button() == Qt.LeftButton:
            eff, kind = self._hit_test(x, y)
            if eff is None:
                if self._selected_id is not None:
                    self._selected_id = None
                    self.update()
                    self.effect_selected.emit(None)
                return
            self._selected_id = eff.id
            self.update()
            self.effect_selected.emit(eff)
            self._drag_id = eff.id
            self._drag_kind = kind
            self._drag_start_x = x
            self._drag_orig_in = eff.in_ms
            self._drag_orig_out = eff.out_ms
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        y = int(event.position().y())
        if self._drag_id is None or self._duration_ms <= 0:
            _, kind = self._hit_test(x, y)
            if kind in ("left", "right"):
                self.setCursor(Qt.SizeHorCursor)
            elif kind == "move":
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.unsetCursor()
            return super().mouseMoveEvent(event)
        body_w = max(1, self.width() - _HEADER_WIDTH)
        delta_ms = int((x - self._drag_start_x) * self._duration_ms / body_w)
        new_in, new_out = self._drag_orig_in, self._drag_orig_out
        if self._drag_kind == "move":
            new_in = self._drag_orig_in + delta_ms
            new_out = self._drag_orig_out + delta_ms
            new_in, new_out = self._snap_pair_to_playhead(new_in, new_out)
            new_in, new_out = self._clamp_move_to_bounds(new_in, new_out)
        elif self._drag_kind == "left":
            new_in = max(0, min(self._drag_orig_out - 100, self._drag_orig_in + delta_ms))
            new_in = self._snap_ms_to_playhead(new_in)
        elif self._drag_kind == "right":
            new_out = max(self._drag_orig_in + 100, self._drag_orig_out + delta_ms)
            new_out = self._snap_ms_to_playhead(new_out)
        new_in = max(0, min(self._duration_ms, new_in))
        new_out = max(0, min(self._duration_ms, new_out))
        if new_out <= new_in:
            return
        eff = next((e for e in self._effects if e.id == self._drag_id), None)
        if eff is None:
            return
        new_eff = replace(eff, in_ms=int(new_in), out_ms=int(new_out))
        self._effects = [new_eff if e.id == self._drag_id else e for e in self._effects]
        self._drag_last_eff = new_eff
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_last_eff is not None:
            self.effect_changed.emit(self._drag_last_eff)
            self._drag_last_eff = None
        self._drag_id = None
        self._drag_kind = None

    # ---------- key ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._selected_id:
            self.effect_deleted.emit(self._selected_id)
            event.accept()
            return
        super().keyPressEvent(event)
