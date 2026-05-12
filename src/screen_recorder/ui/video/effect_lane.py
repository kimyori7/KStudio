"""효과 lane 베이스 위젯 — 효과 종류별 lane 의 공통 base.

Stage 2: 빈 lane (효과 0개) 그리기 + 빈 영역 우클릭 → 시그널.
Stage 3+: 효과별 자식 lane 이 paint/drag/click 을 override 해 막대를 그린다.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QMenu, QWidget


_LANE_HEIGHT = 20
_TRACK_ROW_HEIGHT = 20      # Phase 28 — track_idx 별 row 높이
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

    request_add_at = Signal(int)        # ms — lane 우클릭 메뉴의 자기 type 효과 추가
    # 우클릭 메뉴 '효과 추가' 서브메뉴 — 다른 type 효과 추가 (효과_type, ms).
    request_add_other_at = Signal(str, int)
    request_remove_lane = Signal()      # lane 우클릭 메뉴의 "이 라인 지우기" 선택 시
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
        self._effects: list = []
        # Phase 28 — track_idx 별 row 분리. 외부에서 강제 row 수 보정(빈 lane) 가능.
        self._extra_empty_rows = 0
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

    def effects(self) -> list:
        """이 lane 이 보관 중인 (자기 type 의) 효과들."""
        return list(self._effects)

    def set_effects(self, effects) -> None:
        """외부에서 효과 목록 갱신. 자기 effect_type 만 필터링해 보관.

        Phase 28: track_idx 별 row 분리 — height 가 자동 가변.
        """
        self._effects = [e for e in effects if e.type == self._effect_type]
        self._refresh_height()
        self.update()

    def set_extra_empty_rows(self, n: int) -> None:
        """사용자가 명시적으로 추가한 빈 row 수. 실제 효과 row 외 추가 표시."""
        self._extra_empty_rows = max(0, int(n))
        self._refresh_height()
        self.update()

    def row_count(self) -> int:
        """현재 lane 이 표시 중인 row 수 — 효과 max track_idx + 1, 또는 extra_empty_rows."""
        max_track = 0
        for e in self._effects:
            ti = int(getattr(e, "track_idx", 0))
            if ti > max_track:
                max_track = ti
        used = max_track + 1 if self._effects else 0
        return max(1, used + self._extra_empty_rows)

    def _refresh_height(self) -> None:
        new_h = self.row_count() * _TRACK_ROW_HEIGHT
        if self.height() == new_h:
            return   # 변화 없음 — setFixedHeight 가 layout invalidate 부르는 것 회피.
        self.setFixedHeight(new_h)

    def _track_idx_at_y(self, y: int) -> int:
        """위젯 y 좌표 → track_idx (0-indexed). lane 본체 안 가정."""
        ti = max(0, int(y) // _TRACK_ROW_HEIGHT)
        return min(ti, self.row_count() - 1)

    def _row_y_top(self, track_idx: int) -> int:
        """track_idx 의 row 상단 y. paintEvent / hit_test 에서 사용."""
        return int(track_idx) * _TRACK_ROW_HEIGHT

    # ---------- helpers ----------
    def _x_to_ms(self, x: int) -> int:
        """헤더를 제외한 lane 영역의 x 좌표 → 시간 ms."""
        if self._duration_ms <= 0:
            return 0
        body_width = max(1, self.width() - _HEADER_WIDTH)
        rel = max(0, min(body_width, x - _HEADER_WIDTH))
        return int(round(rel * self._duration_ms / body_width))

    _SNAP_PX = 8
    """효과 박스 edge 가 playhead 와 이 거리(px) 안에 들어오면 정확히 playhead
    위치로 스냅. 사용자 의도 "줌, 배속 등 편집하는게 여기 가까이 가면 달라붙는
    기능" — 빠른 정렬용 magnetism."""

    def _snap_ms_to_playhead(self, ms: int) -> int:
        """ms 가 playhead position 의 ±_SNAP_PX 안에 들어오면 playhead 로 스냅.
        그렇지 않으면 그대로 반환. duration 0 이면 스냅 비활성.
        """
        if self._duration_ms <= 0:
            return ms
        body_width = max(1, self.width() - _HEADER_WIDTH)
        ms_per_px = self._duration_ms / body_width
        threshold_ms = int(round(self._SNAP_PX * ms_per_px))
        if abs(ms - self._position_ms) <= threshold_ms:
            return self._position_ms
        return ms

    def _snap_pair_to_playhead(self, in_ms: int, out_ms: int) -> tuple[int, int]:
        """이동(move) 드래그용 — playhead 에 가까운 쪽 edge 를 스냅하고 반대편은
        같은 만큼 평행 이동. 둘 다 거리가 같으면 in_ms 우선.
        """
        snap_in = self._snap_ms_to_playhead(in_ms)
        snap_out = self._snap_ms_to_playhead(out_ms)
        if snap_in != in_ms and (snap_out == out_ms or
                                   abs(in_ms - self._position_ms) <= abs(out_ms - self._position_ms)):
            shift = snap_in - in_ms
            return in_ms + shift, out_ms + shift
        if snap_out != out_ms:
            shift = snap_out - out_ms
            return in_ms + shift, out_ms + shift
        return in_ms, out_ms

    def _ms_to_x(self, ms: int) -> int:
        if self._duration_ms <= 0:
            return _HEADER_WIDTH
        body_width = max(1, self.width() - _HEADER_WIDTH)
        ratio = max(0.0, min(1.0, ms / self._duration_ms))
        return _HEADER_WIDTH + int(round(ratio * body_width))

    # ---------- paint ----------
    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        # 헤더 영역 — 전체 높이.
        p.fillRect(0, 0, _HEADER_WIDTH, self.height(), _HEADER_BG)
        p.setPen(_HEADER_TEXT)
        p.drawText(6, 0, _HEADER_WIDTH - 8, _TRACK_ROW_HEIGHT,
                   Qt.AlignVCenter | Qt.AlignLeft, self._header_label)
        # 본체 — row 별 배경 + 1px 구분선 (track 시각적 분리).
        body_x = _HEADER_WIDTH
        body_w = self.width() - _HEADER_WIDTH
        rc = self.row_count()
        for ti in range(rc):
            y = self._row_y_top(ti)
            p.fillRect(body_x, y, body_w, _TRACK_ROW_HEIGHT, _BG_COLOR)
            if ti > 0:
                # row 사이 옅은 구분선.
                p.fillRect(body_x, y - 1, body_w, 1, _HEADER_BG)

    # ---------- mouse ----------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton and event.position().x() >= _HEADER_WIDTH:
            ms = self._x_to_ms(int(event.position().x()))
            self._show_lane_context_menu(ms, event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def _show_lane_context_menu(self, ms: int, global_pos) -> None:
        """lane 본체 우클릭 메뉴 — 3단:

        1. 현재 lane type 효과 추가 (예: '+ 캡션 추가')
        2. '효과 추가' 서브메뉴 — 다른 type 효과 (캡션/배속/줌/곁들임/화살표 중 자기 제외)
        3. '이 라인 지우기'

        "1" → request_add_at(ms)
        "2 서브" → request_add_other_at(eff_type, ms)
        "3" → request_remove_lane()
        """
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        # 1. 현재 lane type 추가.
        add_action = QAction(f"+ {self._header_label} 추가", menu)
        add_action.triggered.connect(lambda: self.request_add_at.emit(ms))
        menu.addAction(add_action)
        # 2. 효과 추가 서브메뉴 — 자기 type 제외 모든 효과.
        other_menu = menu.addMenu("효과 추가")
        # 효과 type → 라벨 매핑 (사용자 노출 한글 라벨, 일관성 유지).
        _OTHER_TYPES = [
            ("caption", "캡션"),
            ("speed", "배속"),
            ("zoom", "줌"),
            ("broll", "곁들임"),
            ("arrow", "화살표"),
        ]
        for eff_type, label in _OTHER_TYPES:
            if eff_type == self._effect_type:
                continue
            sub_action = QAction(f"+ {label} 추가", other_menu)
            sub_action.triggered.connect(
                lambda _checked=False, t=eff_type:
                self.request_add_other_at.emit(t, ms)
            )
            other_menu.addAction(sub_action)
        menu.addSeparator()
        # 3. 라인 지우기.
        remove_action = QAction("이 라인 지우기", menu)
        remove_action.triggered.connect(lambda: self.request_remove_lane.emit())
        menu.addAction(remove_action)
        menu.popup(global_pos)

    # ---------- public helpers (페인트/hit 외부 노출) ----------
    TRACK_ROW_HEIGHT = _TRACK_ROW_HEIGHT
