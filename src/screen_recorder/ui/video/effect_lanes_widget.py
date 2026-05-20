"""효과 lane 컨테이너 — 사용된 type 별로 lane 자동 생성."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QVBoxLayout, QWidget

from ...effects import Sidecar
from .arrow_lane import ArrowLane
from .broll_lane import BrollLane
from .caption_lane import CaptionLane
from .cut_lane import CutLane
from .effect_lane import EffectLane
from .speed_lane import SpeedLane
from .zoom_lane import ZoomLane


# type 별 라벨·색 (spec 의 결정 — 추후 i18n 으로 빠질 수도)
_TYPE_LABEL = {
    "caption": "캡션",
    "speed":   "배속",
    "zoom":    "줌",
    "broll":   "곁들임 영상",   # B-roll: 원본 영상 위에 다른 영상을 띄우는 효과
    "arrow":   "화살표",
    "cut":     "자르기 (중간)",   # 자르기 lane 과 통일된 이름. 양 끝 자르기 = TrimMarkerLane.
}
_TYPE_COLOR = {
    "caption": "#3b82f6",   # 파랑
    "speed":   "#8b5cf6",   # 보라
    "zoom":    "#10b981",   # 초록
    "broll":   "#f59e0b",   # 주황
    "arrow":   "#f43f5e",   # 핑크-빨강
    "cut":     "#ef4444",   # 빨강
}

# 효과 lane 의 표시 순서 (위 → 아래).
# 2026-05-19 회귀 fix: cut 이 빠져있어서 사이드카에 cut 효과 있어도 화면에 안 보이던 버그.
# Stage D 의 의도 (cut → 트랙 lane 흡수) 는 video_track_lane.py 에 cut 표시 코드 미구현 상태라
# 사용자가 자동편집/Claude 로 cut 추가해도 시각 피드백 0 → 의도 복구. video_track_lane 에
# cut 흡수 완성되면 그때 다시 제거.
_LANE_ORDER = ["cut", "caption", "speed", "zoom", "broll", "arrow"]

# type → lane 클래스 dispatch. 누락된 type 은 base EffectLane 으로 fallback.
EFFECT_LANE_CLASSES: dict[str, type] = {
    "caption": CaptionLane,
    "cut": CutLane,
    "speed": SpeedLane,
    "zoom": ZoomLane,
    "broll": BrollLane,
    "arrow": ArrowLane,
}


class EffectLanesWidget(QWidget):
    """사이드카에 들어 있는 type 별로 EffectLane 을 자동 생성하는 컨테이너.

    Stage 2: lane 자동 생성·제거 + duration/position 전파 + request_add bubble.
    Stage 3+: 효과별 자식 lane 이 막대 그리기·드래그를 추가.
    """

    request_add = Signal(str, int, int)    # (effect_type, ms, track_idx) — lane 우클릭 add
    # 2026-05-20 (사용자 요청): lane row 의 모든 효과의 enabled 일괄 토글.
    # (effect_type, track_idx, new_enabled) — main_window 가 받아 edit_controller 위임.
    request_toggle_row_enabled = Signal(str, int, bool)
    effect_selected = Signal(object)       # Effect | None — Stage 3+
    effect_changed = Signal(object)        # Effect — Stage 3+
    effect_deleted = Signal(str)           # effect_id — Stage 3+

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._lanes: dict[str, EffectLane] = {}
        # 마지막에 띄운 QMenu — 테스트 검사용. UI 흐름엔 필수 아님.
        self._last_menu: QMenu | None = None
        self._duration_ms = 0
        self._position_ms = 0
        # Phase 28: 복수-라인 type 의 사용자 명시 "빈 row 한 줄" 수.
        # caption/broll/arrow 의 lane 안에서 track_idx 사용량과 별개로 row 가 그려짐.
        self._extra_empty_lanes: dict[str, int] = {}
        # 영상 전환 감지용 — source_hash 가 바뀌면 lane 전부 리셋. 같은 영상 안에서는
        # 효과 변화로 lane 자동 제거 안 함 (사용자 요청: 효과 다 지워도 라인 유지).
        self._last_source_hash: str = ""
        # "이 라인 지우기" 후 effect_deleted emit → sidecar 갱신 → set_sidecar 의 사이클
        # 사이에서 lane 제거 의도 보존. set_sidecar 에서 처리 후 비움.
        self._lanes_pending_removal: set[str] = set()
        # Phase 24: "+ 효과 추가" 행 — 5종 lane 영구 표시 폐기. 효과 없는 lane 은 안 보임.
        self._add_row = QWidget()
        add_row_layout = QHBoxLayout(self._add_row)
        add_row_layout.setContentsMargins(8, 2, 8, 2)
        add_row_layout.setSpacing(4)
        self._add_btn = QPushButton("+ 효과 추가")
        self._add_btn.setFixedHeight(24)
        self._add_btn.setToolTip("현재 재생 위치에 효과 추가 — 종류 선택 메뉴")
        self._add_btn.clicked.connect(self._on_add_button_clicked)
        add_row_layout.addWidget(self._add_btn)
        add_row_layout.addStretch(1)
        self._layout.addWidget(self._add_row)
        # 하단 여백 — timeline area 가 lane 총 높이보다 커지면 마지막 lane 아래에 빈
        # 공간이 자라도록. lane 들은 fixed height 유지 (이전: 잡힐 공간 없이 lane 이
        # 늘어나 video bar 가 두꺼워지던 회귀).
        self._layout.addStretch(1)

    # ---------- public ----------
    def set_sidecar(self, sidecar: Sidecar) -> None:
        """사이드카에 따라 lane 들을 동기화한다.

        Phase 24/28: 효과가 있는 type 의 lane + 사용자가 명시한 빈 lane 표시.

        2026-05-13 정책 변경: 같은 영상 안에서는 효과 0 이라도 lane 유지 (사용자 요청 —
        "효과 다 지웠는데 라인까지 사라지지 않게"). 다른 영상으로 전환 시 (source_hash
        변경) 만 lane 전부 리셋. 명시 "이 라인 지우기" 메뉴는 `_lanes_pending_removal`
        통해 처리.
        """
        new_hash = (getattr(sidecar, "source_hash", "") or "")
        is_video_switch = (new_hash != self._last_source_hash)
        self._last_source_hash = new_hash

        if is_video_switch:
            # 다른 영상으로 전환 — 이전 영상의 lane 인스턴스 전부 폐기.
            for t in list(self._lanes.keys()):
                lane = self._lanes.pop(t)
                self._layout.removeWidget(lane)
                lane.deleteLater()
            self._extra_empty_lanes.clear()
            self._lanes_pending_removal.clear()

        types_in_use = {e.type for e in sidecar.effects if e.type in _LANE_ORDER}
        types_with_extra = {t for t, n in self._extra_empty_lanes.items()
                             if n > 0 and t in _LANE_ORDER}
        all_types = types_in_use | types_with_extra

        # 새로 필요한 type 의 lane 생성 (영상 전환이거나 신규 type 효과 추가 시).
        for t in _LANE_ORDER:
            if t in all_types and t not in self._lanes:
                cls = EFFECT_LANE_CLASSES.get(t, EffectLane)
                lane = cls(
                    effect_type=t,
                    header_label=_TYPE_LABEL.get(t, t),
                    color=_TYPE_COLOR.get(t, "#888888"),
                )
                lane.set_duration_ms(self._duration_ms)
                lane.set_position_ms(self._position_ms)
                self._wire_lane_signals(lane, t)
                self._lanes[t] = lane
                self._insert_lane_in_order(t, lane)

        # 효과 0 이어도 lane 유지 (정책 변경) — 자동 제거 없음.
        # 모든 lane 에 자기 type 의 효과들 + 빈 row 수 전달. 효과 0 이면 빈 lane 표시.
        for t, lane in self._lanes.items():
            lane.set_effects([e for e in sidecar.effects if e.type == t])
            lane.set_extra_empty_rows(self._extra_empty_lanes.get(t, 0))

        # 같은 영상 안에서 명시 "이 라인 지우기" 요청 처리 — 효과/빈 row 모두 0 인 상태에만.
        # **lane 생성/효과 적용 *이후*** 에 수행. 이유: 중간 set_sidecar (intermediate sidecar
        # 가 아직 효과를 갖고 있는 시점) 가 들어와도, 이 시점에선 set_effects 가 lane 에 효과를
        # 다시 넣어 effects() 비어있지 않음 → pending_removal 처리 X. 사이드카가 진짜 효과 0 인
        # 상태로 도착해야 lane.effects()==[] → 그때 처리.
        # 회귀 (2026-05-13: "캡션 라인 지우기 누르면 캡션만 날아가고 라인만 남아있지").
        if not is_video_switch:
            for t in list(self._lanes_pending_removal):
                lane = self._lanes.get(t)
                if lane is None:
                    self._lanes_pending_removal.discard(t)
                    continue
                if not lane.effects() and self._extra_empty_lanes.get(t, 0) <= 0:
                    self._lanes.pop(t)
                    self._layout.removeWidget(lane)
                    lane.deleteLater()
                    self._lanes_pending_removal.discard(t)
                # 효과 / 빈 row 남아있으면 pending 유지 → 다음 set_sidecar 에서 재확인.

    def add_empty_lane(self, effect_type: str) -> None:
        """Phase 28 — 사용자 메뉴 "+ ... 추가" (복수-라인 type) 클릭 시 빈 row 한 줄 추가.

        같은 type 의 lane 이 없으면 만들고, 있으면 row 수를 1 늘림. 효과는 생성 X.
        """
        if effect_type not in _LANE_ORDER:
            return
        self._extra_empty_lanes[effect_type] = self._extra_empty_lanes.get(effect_type, 0) + 1
        # 빈 lane 생성/갱신 — 사이드카 변화는 없지만 UI 만 즉시 반영.
        if effect_type not in self._lanes:
            cls = EFFECT_LANE_CLASSES.get(effect_type, EffectLane)
            lane = cls(
                effect_type=effect_type,
                header_label=_TYPE_LABEL.get(effect_type, effect_type),
                color=_TYPE_COLOR.get(effect_type, "#888888"),
            )
            lane.set_duration_ms(self._duration_ms)
            lane.set_position_ms(self._position_ms)
            self._wire_lane_signals(lane, effect_type)
            self._lanes[effect_type] = lane
            self._insert_lane_in_order(effect_type, lane)
        self._lanes[effect_type].set_extra_empty_rows(self._extra_empty_lanes[effect_type])

    def _wire_lane_signals(self, lane, effect_type: str) -> None:
        """새로 생성한 lane 의 시그널 연결 — set_sidecar / add_empty_lane 공통.

        lane 우클릭 메뉴:
        - "효과 추가" → 빈 row 한 줄을 효과로 채우는 의도. _extra_empty_lanes 감소 후
          request_add.emit. set_sidecar 재호출 시 row 가 (효과 1 + 빈 row N-1) 로 일관.
        - "이 라인 지우기" → 빈 row 줄임. 효과 있는 lane 은 보존.
        """
        lane.request_add_at.connect(
            lambda ms, track_idx, t=effect_type:
            self._on_lane_request_add(t, ms, track_idx)
        )
        # 다른 type 효과 추가 — 빈 row 차감 없이 그냥 emit. track_idx 는 다른 type
        # lane 안에서 자동 결정되므로 그대로 0 전달 (그 lane 의 정책).
        lane.request_add_other_at.connect(
            lambda other_type, ms, track_idx:
            self.request_add.emit(other_type, ms, 0)
        )
        lane.request_remove_lane.connect(
            lambda track_idx, t=effect_type:
            self._on_remove_lane_requested(t, track_idx)
        )
        # 2026-05-20: row 별 활성/비활성 토글 — widget 가 자체 시그널로 다시 emit (외부 wiring).
        lane.request_toggle_row_enabled.connect(self.request_toggle_row_enabled.emit)
        lane.effect_selected.connect(self.effect_selected.emit)
        lane.effect_changed.connect(self.effect_changed.emit)
        lane.effect_deleted.connect(self.effect_deleted.emit)

    def _on_lane_request_add(self, effect_type: str, ms: int, track_idx: int = 0) -> None:
        """lane 우클릭 메뉴 '효과 추가' — 빈 row 한 칸을 effect 로 채우는 의도.

        2026-05-13: track_idx 추가 — 사용자가 *클릭한 row* 의 track_idx 가 effect 의
        track_idx 가 되도록 그대로 위로 전파. 클릭한 빈 row 가 그 자리에서 채워짐.

        _extra_empty_lanes 가 있으면 한 줄 줄여 set_sidecar 재호출 시 row 가 늘지 않게.
        없으면 그냥 request_add (효과 하나 더 추가). 두 경우 모두 main_window 가 효과 생성.
        """
        if self._extra_empty_lanes.get(effect_type, 0) > 0:
            self._extra_empty_lanes[effect_type] -= 1
            if self._extra_empty_lanes[effect_type] <= 0:
                self._extra_empty_lanes.pop(effect_type, None)
        self.request_add.emit(effect_type, ms, track_idx)

    def populate_add_submenu_for_lane(self, sub_menu: QMenu, *,
                                       ms: int, track_idx: int,
                                       exclude_type: Optional[str] = None,
                                       source_lane=None) -> None:
        """lane 우클릭 → '효과 추가' 서브메뉴를 + 효과 추가 버튼 메뉴와 동일 데이터로 빌드.

        2026-05-13: 라벨/단일잠금 검사를 + 효과 추가 메뉴와 통일. track_idx 는 다른
        type 효과 추가 시 그 type lane 자체 정책으로 결정되므로 사용 안 함 (기본 0).
        exclude_type 으로 자기 type 한 가지만 제외.
        """
        sub_menu.setStyleSheet(
            "QMenu::item:disabled { color: #5b6068; }"
            "QMenu::item:disabled:selected { background: transparent; color: #5b6068; }"
        )
        sub_menu.setToolTipsVisible(True)
        for label, eff_type, is_multi, tooltip in self._MENU_ITEMS:
            if exclude_type is not None and eff_type == exclude_type:
                continue
            self._populate_add_action(sub_menu, label, eff_type, is_multi, tooltip, ms)

    def _on_remove_lane_requested(self, effect_type: str, track_idx: int = 0) -> None:
        """lane 우클릭 메뉴 "이 라인 지우기" — 클릭한 row 의 효과·빈 row 모두 정리.

        2026-05-13: 효과가 있어도 동작하도록. 클릭한 row 의 track_idx 에 속한 효과들을
        effect_deleted 시그널로 삭제 (controller 가 sidecar 갱신 → set_sidecar 재호출 →
        lane row 자동 갱신). 사용자 보고 "화살표 있을 때 이 라인 지우기가 안 통함".

        규칙:
        - 해당 row 에 효과가 있으면: 그 효과들 모두 effect_deleted.emit (controller 가 삭제)
        - 빈 row 가 있으면: _extra_empty_lanes 한 줄 줄임
        - 효과·빈 row 모두 없으면 lane 인스턴스 제거 (drag 흐름과 동일하게 set_sidecar 가 처리)
        """
        lane = self._lanes.get(effect_type)
        if lane is None:
            return

        # 1. 클릭한 row 의 track_idx 에 있는 효과들 삭제 시그널.
        # effect_lane.effects() 는 lane 보관 중 자기 type 효과들.
        effects_in_row = [
            e for e in lane.effects()
            if int(getattr(e, "track_idx", 0)) == int(track_idx)
        ]
        if effects_in_row:
            # 사용자가 명시 "이 라인 지우기" — 효과 삭제 + lane 제거 의도.
            # set_sidecar 의 자동 제거가 비활성화돼 있으므로 명시 큐에 등록.
            # 단, 다른 track_idx 에 효과가 남아 있거나 빈 row 가 있으면 lane 유지.
            remaining_effects = [e for e in lane.effects() if e not in effects_in_row]
            has_extra_empty = self._extra_empty_lanes.get(effect_type, 0) > 0
            if not remaining_effects and not has_extra_empty:
                self._lanes_pending_removal.add(effect_type)
            for e in effects_in_row:
                self.effect_deleted.emit(e.id)
            # 효과 삭제 후 sidecar_replaced → set_sidecar 가 pending_removal 처리.
            return

        # 2. 빈 row 처리 (기존 로직).
        if self._extra_empty_lanes.get(effect_type, 0) > 0:
            self._extra_empty_lanes[effect_type] -= 1
            remaining_extra = self._extra_empty_lanes[effect_type]
            if remaining_extra <= 0:
                self._extra_empty_lanes.pop(effect_type, None)
            lane.set_extra_empty_rows(remaining_extra)
            # 빈 row 0 이고 효과도 0 인 경우만 lane 자체 제거.
            if remaining_extra <= 0 and not lane.effects():
                self._lanes.pop(effect_type)
                self._layout.removeWidget(lane)
                lane.deleteLater()
            return

    def set_duration_ms(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        for lane in self._lanes.values():
            lane.set_duration_ms(ms)

    def set_position_ms(self, ms: int) -> None:
        self._position_ms = max(0, int(ms))
        for lane in self._lanes.values():
            lane.set_position_ms(ms)

    def lane_count(self) -> int:
        return len(self._lanes)

    def has_lane_for_type(self, effect_type: str) -> bool:
        return effect_type in self._lanes

    def lane_for_type(self, effect_type: str) -> Optional[EffectLane]:
        return self._lanes.get(effect_type)

    # ---------- internal ----------
    def _insert_lane_in_order(self, effect_type: str, lane: EffectLane) -> None:
        """정해진 _LANE_ORDER 에 맞는 위치에 lane 삽입. _add_row 는 항상 맨 아래."""
        target_rank = _LANE_ORDER.index(effect_type)
        # 기본값: _add_row 직전. _add_row 는 set_sidecar 호출 전부터 존재.
        add_row_index = self._layout.indexOf(self._add_row)
        insert_at = add_row_index if add_row_index >= 0 else self._layout.count()
        for i in range(self._layout.count()):
            existing = self._layout.itemAt(i).widget()
            if not isinstance(existing, EffectLane):
                continue
            if _LANE_ORDER.index(existing.effect_type()) > target_rank:
                insert_at = i
                break
        self._layout.insertWidget(insert_at, lane)

    def _on_add_button_clicked(self) -> None:
        """+ 효과 추가 버튼 클릭 → 현재 재생 위치에 효과 추가 메뉴."""
        self._show_add_menu_at(self._position_ms)

    # 통합 추가 메뉴 — Phase 27: 라인 개수 정책에 따른 라벨 + 단일-라인 잠금.
    # multi=True 면 같은 type 효과 동시 가능 (Phase 21 track_idx). multi=False 면 lane 한 줄만.
    _MENU_ITEMS: list[tuple[str, str, bool, str]] = [
        # (label, effect_type, is_multi, tooltip)
        ("+ 캡션 추가 (복수 가능)",          "caption", True,
         "여러 캡션을 같은 시간에 동시에 표시할 수 있음"),
        ("+ 배속 추가 (단일)",               "speed",   False,
         "배속은 영상 전체 시간을 늘리거나 줄이므로 한 줄만 가능"),
        ("+ 줌 추가 (단일)",                 "zoom",    False,
         "줌은 한 시점에 하나만 — 단일 라인"),
        ("+ 곁들임 영상 추가 (복수 가능)",   "broll",   True,
         "여러 곁들임 영상을 PiP 로 동시에 띄울 수 있음"),
        ("+ 화살표 추가 (복수 가능)",        "arrow",   True,
         "여러 화살표를 동시에 띄울 수 있음"),
    ]

    def _show_add_menu_at(self, ms: int) -> None:
        """어느 lane 의 우클릭이든 호출. 5 항목 통합 메뉴.

        Phase 27/28: 단일-라인 type 은 이미 효과가 있으면 비활성. 복수-라인 type 은
        클릭 시 빈 row 한 줄만 추가 (효과는 lane 안 우클릭으로 별도). 단일-라인 type 은
        클릭 시 즉시 효과 생성 (현재 흐름).
        """
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        # 비활성 항목이 명확히 흐릿하게 보이도록 — Qt 기본 disabled 색이 다크 테마에선
        # 너무 약함. 별도 stylesheet 로 disabled 텍스트 색 + (이미 있음) 부가 라벨.
        menu.setStyleSheet(
            "QMenu::item:disabled { color: #5b6068; }"
            "QMenu::item:disabled:selected { background: transparent; color: #5b6068; }"
        )
        for label, eff_type, is_multi, tooltip in self._MENU_ITEMS:
            self._populate_add_action(menu, label, eff_type, is_multi, tooltip, ms)
        menu.setToolTipsVisible(True)
        self._last_menu = menu
        menu.popup(QCursor.pos())

    def populate_add_submenu(self, sub_menu: QMenu, ms: int,
                              exclude_type: Optional[str] = None) -> None:
        """라인 우클릭 → '효과 추가' 서브메뉴와 + 효과 추가 버튼 메뉴를 같은 데이터로 통일.

        2026-05-13: 사용자 보고 — 서브메뉴 라벨과 + 효과 추가 메뉴 라벨이 달랐음.
        같은 _MENU_ITEMS 와 단일/이미있음 검사 로직을 공유하도록 위임 API 노출.
        exclude_type 으로 자기 type 한 가지만 제외 (lane 우클릭의 첫 항목과 중복 회피).
        """
        sub_menu.setStyleSheet(
            "QMenu::item:disabled { color: #5b6068; }"
            "QMenu::item:disabled:selected { background: transparent; color: #5b6068; }"
        )
        sub_menu.setToolTipsVisible(True)
        for label, eff_type, is_multi, tooltip in self._MENU_ITEMS:
            if exclude_type is not None and eff_type == exclude_type:
                continue
            self._populate_add_action(sub_menu, label, eff_type, is_multi, tooltip, ms)

    def label_for_type(self, eff_type: str) -> Optional[str]:
        """_MENU_ITEMS 의 통일 라벨 ("+ 캡션 추가 (복수 가능)" 등). 없으면 None."""
        for label, t, _is_multi, _tip in self._MENU_ITEMS:
            if t == eff_type:
                return label
        return None

    def _populate_add_action(self, menu: QMenu, label: str, eff_type: str,
                              is_multi: bool, tooltip: str, ms: int) -> None:
        """_MENU_ITEMS 한 항목을 QAction 으로 빌드해 menu 에 추가 — 단일/이미있음 검사 포함."""
        locked = (not is_multi) and (eff_type in self._lanes
                                      and len(self._lanes[eff_type].effects()) > 0)
        text = f"{label}   ✓ 이미 있음" if locked else label
        action = QAction(text, menu)
        enabled = not locked
        action.setEnabled(enabled)
        if locked:
            action.setToolTip("이미 추가됨 — 단일 라인만 가능. 기존 항목을 편집하세요.")
        elif tooltip:
            action.setToolTip(tooltip)
        if enabled:
            if is_multi:
                action.triggered.connect(
                    lambda _checked=False, t=eff_type: self.add_empty_lane(t)
                )
            else:
                action.triggered.connect(
                    lambda _checked=False, t=eff_type, m=ms:
                    self.request_add.emit(t, m, 0)
                )
        menu.addAction(action)
