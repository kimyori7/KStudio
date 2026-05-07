"""CutLane — cut 효과의 lane 자식 클래스.

3 시각 모드:
- splice (in == out): 가는 세로 마커 (회색 ±2px, 클릭 hit 영역 ±5px)
- 구간 자르기 (src 비어있음): 회색 빗금 막대 — "잘려나간 빈 구간 / 영상 추가 가능" 신호
- 자르기 + 영상 (src 채워짐): 청록 채움 막대 + ▶ + 파일명 + B 길이 라벨

drag/hit-test/Delete 는 CaptionLane 과 동일 패턴.
"""
from __future__ import annotations
import os
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen,
)

from ...effects.types.cut import CutEffect
from .effect_lane import EffectLane


_HEADER_WIDTH = 56
_BAR_RADIUS = 3
_EDGE_HANDLE_PX = 5
_SPLICE_HALF_WIDTH = 2          # 세로 마커 폭 절반 (paint)
_SPLICE_HIT_HALF = 5            # 세로 마커 hit-test 영역 절반

_SPLICE_COLOR = QColor(220, 220, 220, 230)
_SPLICE_BORDER = QColor(0, 0, 0, 220)

_RANGE_NO_INSERT_BG = QColor(120, 120, 120, 120)        # 회색 반투명
_RANGE_NO_INSERT_HATCH = QColor(180, 180, 180, 200)
_RANGE_NO_INSERT_BORDER = QColor(60, 60, 60, 220)

_RANGE_INSERT_BG = QColor(20, 184, 166, 180)            # 청록
_RANGE_INSERT_BG_SELECTED = QColor(45, 212, 191, 230)
_RANGE_INSERT_BORDER = QColor(0, 0, 0, 220)
_RANGE_INSERT_BORDER_SELECTED = QColor(255, 255, 255, 230)
_TEXT_COLOR = QColor(255, 255, 255, 230)
_TEXT_DARK = QColor(40, 40, 40, 230)


def _ms_to_label(ms: int) -> str:
    """1234 → '1.2s', 12345 → '12.3s'."""
    return f"{ms / 1000.0:.1f}s"


class CutLane(EffectLane):
    """cut 효과 lane — 3 모드 paint, drag, Delete."""

    def __init__(self, effect_type: str, header_label: str, color: str) -> None:
        super().__init__(effect_type, header_label, color)
        self.setFocusPolicy(Qt.StrongFocus)
        self._selected_id: Optional[str] = None
        self._drag_id: Optional[str] = None
        self._drag_kind: Optional[str] = None
        self._drag_start_x: int = 0
        self._drag_orig_in: int = 0
        self._drag_orig_out: int = 0

    def selected_id(self) -> Optional[str]:
        return self._selected_id

    # ---------- helpers ----------
    def _bar_rect_for(self, eff: CutEffect):
        return self._ms_to_x(eff.in_ms), self._ms_to_x(eff.out_ms)

    def _hit_test(self, x: int):
        if x < _HEADER_WIDTH:
            return None, None
        for eff in self._effects:
            x1, x2 = self._bar_rect_for(eff)
            if eff.is_splice:
                # splice point — ±5px hit
                if abs(x - x1) <= _SPLICE_HIT_HALF:
                    return eff, "move"
                continue
            if x1 <= x <= x2:
                if x - x1 <= _EDGE_HANDLE_PX:
                    return eff, "left"
                if x2 - x <= _EDGE_HANDLE_PX:
                    return eff, "right"
                return eff, "move"
        return None, None

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._duration_ms <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for eff in self._effects:
            x1, x2 = self._bar_rect_for(eff)
            selected = (eff.id == self._selected_id)
            if eff.is_splice:
                self._paint_splice(p, x1, selected)
            elif eff.has_insert:
                self._paint_range_with_insert(p, x1, x2, eff, selected)
            else:
                self._paint_range_no_insert(p, x1, x2, selected)

    def _paint_splice(self, p: QPainter, x: int, selected: bool) -> None:
        pen = QPen(_SPLICE_BORDER)
        pen.setWidth(2 if selected else 1)
        p.setPen(pen)
        p.setBrush(_SPLICE_COLOR)
        p.drawRect(x - _SPLICE_HALF_WIDTH, 2,
                   _SPLICE_HALF_WIDTH * 2, self.height() - 4)

    def _paint_range_no_insert(self, p: QPainter, x1: int, x2: int, selected: bool) -> None:
        if x2 <= x1:
            return
        pen = QPen(_RANGE_NO_INSERT_BORDER)
        pen.setWidth(2 if selected else 1)
        p.setPen(pen)
        brush = QBrush(_RANGE_NO_INSERT_HATCH, Qt.BDiagPattern)
        p.setBrush(brush)
        p.drawRoundedRect(x1, 2, x2 - x1, self.height() - 4, _BAR_RADIUS, _BAR_RADIUS)
        if x2 - x1 > 60:
            p.setPen(_TEXT_DARK)
            p.drawText(x1 + 4, 0, x2 - x1 - 8, self.height(),
                       Qt.AlignVCenter | Qt.AlignLeft, "+ 영상 넣기")

    def _paint_range_with_insert(self, p: QPainter, x1: int, x2: int,
                                 eff: CutEffect, selected: bool) -> None:
        if x2 <= x1:
            return
        p.setBrush(_RANGE_INSERT_BG_SELECTED if selected else _RANGE_INSERT_BG)
        pen = QPen(_RANGE_INSERT_BORDER_SELECTED if selected else _RANGE_INSERT_BORDER)
        pen.setWidth(2 if selected else 1)
        p.setPen(pen)
        p.drawRoundedRect(x1, 2, x2 - x1, self.height() - 4, _BAR_RADIUS, _BAR_RADIUS)
        if x2 - x1 > 30:
            p.setPen(_TEXT_COLOR)
            name = os.path.basename(eff.src) if eff.src else ""
            label = f"▶ {name} ({_ms_to_label(eff.insert_duration_ms)})"
            p.drawText(x1 + 4, 0, x2 - x1 - 8, self.height(),
                       Qt.AlignVCenter | Qt.AlignLeft, label)

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        if event.button() == Qt.LeftButton:
            eff, kind = self._hit_test(x)
            if eff is None:
                if self._selected_id is not None:
                    self._selected_id = None
                    self.update()
                    self.effect_selected.emit(None)
                # 빈 영역에서는 우클릭만 add — base 가 처리
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
        # 드래그 중이 아니면 hover 커서 갱신 후 종료.
        if self._drag_id is None or self._duration_ms <= 0:
            eff_hit, kind = self._hit_test(x)
            # splice 는 좁은 마커라 hover 시 항상 SizeAllCursor (move). 구간은 left/right edge 가 ↔.
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
        eff = next((e for e in self._effects if e.id == self._drag_id), None)
        if eff is None:
            return
        if self._drag_kind == "move":
            new_in = self._drag_orig_in + delta_ms
            new_out = self._drag_orig_out + delta_ms
        elif self._drag_kind == "left" and not eff.is_splice:
            # 구간만 left 핸들 의미. 최소 100ms 폭 유지.
            new_in = max(0, min(self._drag_orig_out - 100, self._drag_orig_in + delta_ms))
        elif self._drag_kind == "right" and not eff.is_splice:
            new_out = max(self._drag_orig_in + 100, self._drag_orig_out + delta_ms)
        new_in = max(0, min(self._duration_ms, new_in))
        new_out = max(0, min(self._duration_ms, new_out))
        # splice 는 in == out 유지. 구간은 out > in 유지.
        if eff.is_splice:
            new_out = new_in
        elif new_out <= new_in:
            return
        new_eff = replace(eff, in_ms=int(new_in), out_ms=int(new_out))
        self._effects = [new_eff if e.id == self._drag_id else e for e in self._effects]
        self.update()
        self.effect_changed.emit(new_eff)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_id = None
        self._drag_kind = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        if event.button() == Qt.LeftButton:
            eff, _kind = self._hit_test(x)
            if eff is not None:
                self._selected_id = eff.id
                self.update()
                self.effect_selected.emit(eff)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    # ---------- key ----------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._selected_id:
            self.effect_deleted.emit(self._selected_id)
            event.accept()
            return
        super().keyPressEvent(event)
