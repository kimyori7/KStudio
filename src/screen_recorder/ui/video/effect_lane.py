"""효과 lane 베이스 위젯 — 효과 종류별 lane 의 공통 base.

Stage 2: 빈 lane (효과 0개) 그리기 + 빈 영역 우클릭 → 시그널.
Stage 3+: 효과별 자식 lane 이 paint/drag/click 을 override 해 막대를 그린다.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


_LANE_HEIGHT = 20
_HEADER_WIDTH = 56
_BG_COLOR = QColor(40, 44, 52)
_HEADER_BG = QColor(30, 33, 39)
_HEADER_TEXT = QColor(180, 190, 200)


class EffectLane(QWidget):
    """효과 한 종류의 시간축 lane.

    - effect_type: "caption" / "speed" / "zoom" / "broll" / "cut"
    - header_label: 좌측에 표시할 짧은 라벨 (예: "캡션")
    - color_hex: lane 본체의 강조 색 (효과 막대에 사용)
    """

    request_add_at = Signal(int)        # ms — 빈 영역 우클릭 시
    effect_selected = Signal(object)    # Effect | None — 막대 클릭 (Stage 3+ 에서 사용)
    effect_changed = Signal(object)     # Effect — 막대 드래그/길이 조정 (Stage 3+)
    effect_deleted = Signal(str)        # effect_id — Delete 키 (Stage 3+)

    def __init__(self, effect_type: str, header_label: str, color: str) -> None:
        super().__init__()
        self._effect_type = effect_type
        self._header_label = header_label
        self._color = QColor(color)
        self._color_hex = color
        self._duration_ms = 0
        self._position_ms = 0
        self.setFixedHeight(_LANE_HEIGHT)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.PreventContextMenu)  # 우클릭은 우리 시그널로

    # ---------- 외부 API ----------
    def effect_type(self) -> str:
        return self._effect_type

    def header_label(self) -> str:
        return self._header_label

    def color_hex(self) -> str:
        return self._color_hex

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self._position_ms

    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        self.update()

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        self.update()

    # ---------- helpers ----------
    def _x_to_ms(self, x: int) -> int:
        """헤더를 제외한 lane 영역의 x 좌표 → 시간 ms."""
        if self._duration_ms <= 0:
            return 0
        body_width = max(1, self.width() - _HEADER_WIDTH)
        rel = max(0, min(body_width, x - _HEADER_WIDTH))
        return int(rel * self._duration_ms / body_width)

    def _ms_to_x(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return _HEADER_WIDTH
        body_width = max(1, self.width() - _HEADER_WIDTH)
        return _HEADER_WIDTH + int(ms * body_width / self._duration_ms)

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        # 헤더 영역
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_TEXT)
        p.drawText(6, 0, _HEADER_WIDTH - 8, self.height(),
                   Qt.AlignVCenter | Qt.AlignLeft, self._header_label)
        # 본체 (빈 상태 — 단순 배경)
        p.fillRect(_HEADER_WIDTH, 0, self.width() - _HEADER_WIDTH, self.height(), _BG_COLOR)

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton and event.position().x() >= _HEADER_WIDTH:
            ms = self._x_to_ms(int(event.position().x()))
            self.request_add_at.emit(ms)
            event.accept()
            return
        super().mousePressEvent(event)
