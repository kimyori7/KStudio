"""CaptionLane — caption 효과의 lane 자식 클래스.

막대 그리기 + 클릭 선택 + 좌우 드래그(시간 이동) + 양 끝 드래그(길이 조정) +
Delete 삭제. 외부에서는 set_effects / effects / selected_id / 시그널만 사용.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (
    QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen,
)

from ...effects.types.caption import CaptionEffect
from .effect_lane import EffectLane


_HEADER_WIDTH = 56              # base 와 동일
_BAR_RADIUS = 3
_EDGE_HANDLE_PX = 5
_BAR_BG = QColor(59, 130, 246, 180)        # caption 색 + 알파
_BAR_BG_SELECTED = QColor(96, 165, 250, 230)
_BAR_BORDER = QColor(0, 0, 0, 220)
_BAR_BORDER_SELECTED = QColor(255, 255, 255, 230)
_TEXT_COLOR = QColor(255, 255, 255, 230)


class CaptionLane(EffectLane):
    """캡션 효과 lane — 막대 그리기·드래그·삭제."""

    def __init__(self, effect_type: str, header_label: str, color: str) -> None:
        super().__init__(effect_type, header_label, color)
        self.setFocusPolicy(Qt.StrongFocus)   # Delete 키를 받으려면 포커스 필요
        self._selected_id: Optional[str] = None
        # 드래그 상태
        self._drag_id: Optional[str] = None
        self._drag_kind: Optional[str] = None       # "move" / "left" / "right"
        self._drag_start_x: int = 0
        self._drag_orig_in: int = 0
        self._drag_orig_out: int = 0
        self._drag_last_eff = None

    # ---------- public ----------
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    # ---------- helpers ----------
    def _bar_rect_for(self, eff: CaptionEffect):
        """효과의 lane 안 좌표 (x_start, x_end). 헤더 제외 본체 좌표계."""
        x1 = self._ms_to_x(eff.in_ms)
        x2 = self._ms_to_x(eff.out_ms)
        return x1, x2

    def _hit_test(self, x: int, y: int | None = None):
        """포인터 (x, y) → (effect, kind). y 가 주어지면 track_idx 매칭도 검사.

        kind: "left"/"right"/"move".
        """
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

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)   # 헤더·배경 (row 분리 포함)
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
                snippet = eff.text.replace("\n", " ")[:20]
                p.drawText(x1 + 4, row_top, x2 - x1 - 8, self.TRACK_ROW_HEIGHT,
                           Qt.AlignVCenter | Qt.AlignLeft, snippet)
        # 2026-05-20: 비활성 row dim overlay.
        self._paint_disabled_overlay(p)

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = int(event.position().x())
        y = int(event.position().y())
        if event.button() == Qt.LeftButton:
            eff, kind = self._hit_test(x, y)
            if eff is None:
                # 빈 영역 좌클릭 → 선택 해제
                if self._selected_id is not None:
                    self._selected_id = None
                    self.update()
                    self.effect_selected.emit(None)
                return
            self._selected_id = eff.id
            self.update()
            self.effect_selected.emit(eff)
            # 드래그 시작 상태 기록
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
        # 드래그 중이 아니면 hover 커서 갱신 후 종료.
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
        # 같은 row 이웃에 딱 붙도록 클램프 — 겹쳐서 원복되던 동작 대신 flush (2026-06-23).
        _ti = int(getattr(
            next((e for e in self._effects if e.id == self._drag_id), None),
            "track_idx", 0))
        new_in, new_out = self._clamp_against_siblings(
            self._drag_kind, new_in, new_out, drag_id=self._drag_id,
            orig_in=self._drag_orig_in, orig_out=self._drag_orig_out, track_idx=_ti)
        # clamp 0..duration
        new_in = max(0, min(self._duration_ms, new_in))
        new_out = max(0, min(self._duration_ms, new_out))
        if new_out <= new_in:
            return
        # 새 effect 만들어 emit (immutable update)
        eff = next((e for e in self._effects if e.id == self._drag_id), None)
        if eff is None:
            return
        # CaptionEffect 의 dataclass — replace 필드만 변경한 새 인스턴스
        from dataclasses import replace
        new_eff = replace(eff, in_ms=int(new_in), out_ms=int(new_out))
        # local 즉시 갱신 (중간 상태) — 외부가 set_effects 로 다시 줄 때까지 시각만
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
