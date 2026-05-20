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

    # ms, track_idx — lane 우클릭 메뉴의 자기 type 효과 추가. track_idx 는 클릭한 row
    # 의 sub-lane 인덱스 (Phase 28: 같은 type 의 여러 row 가 쌓일 수 있음). 사용자가
    # *클릭한 row* 의 track_idx 에 효과가 들어가도록 시그널에 함께 전달.
    request_add_at = Signal(int, int)
    # 우클릭 메뉴 '효과 추가' 서브메뉴 — 다른 type 효과 추가 (효과_type, ms, track_idx).
    # track_idx 는 다른 type lane 안에서 의미 — main_window 핸들러가 정책 결정.
    request_add_other_at = Signal(str, int, int)
    # "이 라인 지우기" — track_idx 함께 emit. 효과가 있는 row 면 그 row 의 효과들도
    # 삭제 (effect_lanes_widget이 effect_deleted 로 전파). 빈 row 면 row 자체만 줄임.
    request_remove_lane = Signal(int)
    # 2026-05-20 (사용자 요청): lane row 의 모든 효과의 enabled 일괄 토글.
    # (effect_type, track_idx, new_enabled) — effect_lanes_widget 이 받아 edit_controller 위임.
    request_toggle_row_enabled = Signal(str, int, bool)
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

    def _clamp_move_to_bounds(self, new_in: int, new_out: int) -> tuple[int, int]:
        """평행 이동(move) 드래그용 — (in, out) 한 쌍을 [0, duration] 안으로 *평행* 이동.

        2026-05-19 사용자 보고 회귀 fix: 기존 코드는 in 과 out 을 독립 클램프 →
        in 이 0 에 막히면 out 만 계속 줄어 효과 폭이 좁아짐 ("왼쪽 끝 도달했는데
        오른쪽이 줄어드는" 증상).

        새 규칙:
        - new_in < 0 이면 그만큼 *함께* 우측 shift → 폭 보존
        - new_out > duration 이면 그만큼 *함께* 좌측 shift → 폭 보존
        - 효과 폭이 영상 길이보다 크면 (드문 경우) 전체 [0, duration] 으로 클램프
        - left/right edge 드래그(폭 조정) 에는 사용 금지 — 그 쪽은 독립 클램프가 정답
        """
        width = new_out - new_in
        # 폭이 영상보다 크면 평행 이동 불가능 — 전체 클램프.
        if width >= self._duration_ms:
            return 0, max(0, int(self._duration_ms))
        if new_in < 0:
            shift = -new_in
            new_in += shift
            new_out += shift
        if new_out > self._duration_ms:
            shift = new_out - self._duration_ms
            new_in -= shift
            new_out -= shift
        return int(new_in), int(new_out)

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
            # 2026-05-13: 클릭한 *row* 의 track_idx 계산 — 사용자 보고 "라인 누르고
            # 화살표 추가하면 클릭한 라인 지워지고 맨 위 라인에 효과 생김" fix.
            ti = self._track_idx_at_y(int(event.position().y()))
            self._show_lane_context_menu(ms, ti, event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def _show_lane_context_menu(self, ms: int, track_idx: int, global_pos) -> None:
        """lane 본체 우클릭 메뉴 — 3단:

        1. 현재 lane type 효과 추가 (예: '+ 캡션 추가 (복수 가능)')
        2. '효과 추가' 서브메뉴 — 자기 type 제외 (라벨은 + 효과 추가 메뉴와 동일)
        3. '이 라인 지우기'

        2026-05-13: 메뉴 라벨이 부모(EffectLanesWidget)의 + 효과 추가 버튼 메뉴와
        일치하도록 위임 (label_for_type, populate_add_submenu). 단일/이미있음 검사
        로직도 한 곳에서.
        """
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)

        # 부모 EffectLanesWidget (단일 진실의 원천) 가 메뉴 라벨/lock 정보를 제공.
        parent = self.parentWidget()
        unified_label = None
        if parent is not None and hasattr(parent, "label_for_type"):
            unified_label = parent.label_for_type(self._effect_type)

        # 1. 현재 lane type 추가 — 통일 라벨 사용 (예: "+ 캡션 추가 (복수 가능)").
        add_label = unified_label or f"+ {self._header_label} 추가"
        add_action = QAction(add_label, menu)
        add_action.triggered.connect(
            lambda _checked=False, m=ms, ti=track_idx:
            self.request_add_at.emit(m, ti)
        )
        menu.addAction(add_action)

        # 2. 효과 추가 서브메뉴 — 부모에 위임. + 효과 추가 버튼 메뉴와 완전 동일 (5개).
        # 자기 type 도 포함 — 서브 안 자기 type 클릭은 "빈 라인 한 줄 더 추가"
        # (= add_empty_lane). 첫 항목 "+ 화살표 추가" 와 별개 — 첫 항목은 *클릭한
        # row 에 효과 즉시* 추가, 서브 안 자기 type 항목은 빈 라인 row 추가.
        other_menu = menu.addMenu("효과 추가")
        if parent is not None and hasattr(parent, "populate_add_submenu_for_lane"):
            parent.populate_add_submenu_for_lane(
                other_menu, ms=ms, track_idx=track_idx,
                exclude_type=None, source_lane=self,
            )
        elif parent is not None and hasattr(parent, "populate_add_submenu"):
            parent.populate_add_submenu(other_menu, ms=ms, exclude_type=None)

        menu.addSeparator()
        # 2026-05-20 (사용자 요청): 이 row 의 모든 효과 활성/비활성 토글.
        # 효과가 있는 row 에서만 표시 — 빈 row 면 의미 없음.
        row_effects = [
            e for e in self._effects
            if int(getattr(e, "track_idx", 0)) == int(track_idx)
        ]
        if row_effects:
            all_disabled = all(not bool(getattr(e, "enabled", True)) for e in row_effects)
            toggle_label = "이 라인 활성화" if all_disabled else "이 라인 비활성화"
            toggle_action = QAction(toggle_label, menu)
            toggle_action.triggered.connect(
                lambda _checked=False, ti=track_idx, new_on=all_disabled:
                self.request_toggle_row_enabled.emit(self._effect_type, ti, new_on)
            )
            menu.addAction(toggle_action)

        # 3. 라인 지우기 — type 라벨 명시해 어떤 lane 인지 한눈에 (사용자 보고 2026-05-13).
        # header_label 우선, 없으면 effect_type 그대로.
        type_label = self._header_label or self._effect_type
        remove_action = QAction(f"{type_label} 라인 지우기", menu)
        remove_action.triggered.connect(
            lambda _checked=False, ti=track_idx: self.request_remove_lane.emit(ti)
        )
        menu.addAction(remove_action)
        menu.popup(global_pos)

    # ---------- 2026-05-20: 비활성 row 시각 dim ----------
    def _paint_disabled_overlay(self, p: QPainter) -> None:
        """비활성 row 위에 반투명 어두운 overlay — 사용자가 OFF 인지 한눈에 식별.

        같은 track_idx 의 모든 효과가 enabled=False 면 그 row 전체를 dim.
        각 자식 lane 의 paintEvent 끝에 호출.
        """
        # row 별 효과 묶음.
        by_row: dict[int, list] = {}
        for e in self._effects:
            ti = int(getattr(e, "track_idx", 0))
            by_row.setdefault(ti, []).append(e)
        if not by_row:
            return
        disabled_rows = [
            ti for ti, effs in by_row.items()
            if effs and all(not bool(getattr(e, "enabled", True)) for e in effs)
        ]
        if not disabled_rows:
            return
        body_x = _HEADER_WIDTH
        body_w = self.width() - _HEADER_WIDTH
        overlay = QColor(0, 0, 0, 130)   # 검은 반투명 — 효과 막대 위에 덮어 dim.
        for ti in disabled_rows:
            y = self._row_y_top(ti)
            p.fillRect(body_x, y, body_w, _TRACK_ROW_HEIGHT, overlay)

    # ---------- public helpers (페인트/hit 외부 노출) ----------
    TRACK_ROW_HEIGHT = _TRACK_ROW_HEIGHT
