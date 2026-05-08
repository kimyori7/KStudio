"""효과 lane 컨테이너 — 사용된 type 별로 lane 자동 생성."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from ...effects import Sidecar
from .caption_lane import CaptionLane
from .cut_lane import CutLane
from .effect_lane import EffectLane
from .speed_lane import SpeedLane


# type 별 라벨·색 (spec 의 결정 — 추후 i18n 으로 빠질 수도)
_TYPE_LABEL = {
    "caption": "캡션",
    "speed":   "배속",
    "zoom":    "줌",
    "broll":   "곁들임 영상",   # B-roll: 원본 영상 위에 다른 영상을 띄우는 효과
    "cut":     "자르기 (중간)",   # 자르기 lane 과 통일된 이름. 양 끝 자르기 = TrimMarkerLane.
}
_TYPE_COLOR = {
    "caption": "#3b82f6",   # 파랑
    "speed":   "#8b5cf6",   # 보라
    "zoom":    "#10b981",   # 초록
    "broll":   "#f59e0b",   # 주황
    "cut":     "#ef4444",   # 빨강
}

# 효과 lane 의 표시 순서 (위 → 아래) — spec 의 RENDER_ORDER 와 일관
_LANE_ORDER = ["caption", "speed", "zoom", "broll", "cut"]

# type → lane 클래스 dispatch. 누락된 type 은 base EffectLane 으로 fallback.
EFFECT_LANE_CLASSES: dict[str, type] = {
    "caption": CaptionLane,
    "cut": CutLane,
    "speed": SpeedLane,
}


class EffectLanesWidget(QWidget):
    """사이드카에 들어 있는 type 별로 EffectLane 을 자동 생성하는 컨테이너.

    Stage 2: lane 자동 생성·제거 + duration/position 전파 + request_add bubble.
    Stage 3+: 효과별 자식 lane 이 막대 그리기·드래그를 추가.
    """

    request_add = Signal(str, int)         # (effect_type, ms) — lane 우클릭 add
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

    # ---------- public ----------
    def set_sidecar(self, sidecar: Sidecar) -> None:
        """사이드카에 따라 lane 들을 동기화한다.

        편집 모드 진입 시 사용자가 즉시 lane 영역을 볼 수 있도록 _LANE_ORDER 의 모든
        type 에 대해 lane 을 만든다 (효과 0 개여도 빈 lane 표시). 효과 type 별 막대는
        해당 lane 안에 그려진다.
        """
        # _LANE_ORDER 의 모든 type 에 대해 lane 생성 (없으면). 정해진 순서대로.
        for t in _LANE_ORDER:
            if t not in self._lanes:
                cls = EFFECT_LANE_CLASSES.get(t, EffectLane)
                lane = cls(
                    effect_type=t,
                    header_label=_TYPE_LABEL.get(t, t),
                    color=_TYPE_COLOR.get(t, "#888888"),
                )
                lane.set_duration_ms(self._duration_ms)
                lane.set_position_ms(self._position_ms)
                lane.request_add_at.connect(self._show_add_menu_at)
                lane.effect_selected.connect(self.effect_selected.emit)
                lane.effect_changed.connect(self.effect_changed.emit)
                lane.effect_deleted.connect(self.effect_deleted.emit)
                self._lanes[t] = lane
                self._insert_lane_in_order(t, lane)

        # 모든 lane 에 자기 type 의 효과들 전달
        for t, lane in self._lanes.items():
            lane.set_effects([e for e in sidecar.effects if e.type == t])

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
        """정해진 _LANE_ORDER 에 맞는 위치에 lane 삽입."""
        target_rank = _LANE_ORDER.index(effect_type)
        insert_at = self._layout.count()
        for i in range(self._layout.count()):
            existing = self._layout.itemAt(i).widget()
            if not isinstance(existing, EffectLane):
                continue
            if _LANE_ORDER.index(existing.effect_type()) > target_rank:
                insert_at = i
                break
        self._layout.insertWidget(insert_at, lane)

    # 통합 추가 메뉴 — caption/cut splice/cut range 활성, speed/zoom/broll 비활성+툴팁.
    _MENU_ITEMS: list[tuple[str, str, bool, str]] = [
        # (label, effect_type, enabled, tooltip)
        ("+ 캡션 추가",                "caption",    True,  ""),
        ("+ 자르기 (한 점)",            "cut_splice", True,  "현재 위치에서 잘라 붙이기 (길이 0) — 양쪽이 한 프레임에서 끊겨 이어짐"),
        ("+ 자르기 (구간)",             "cut_range",  True,  "구간 잘라내기 — 1초 길이로 시작, 인스펙터에서 길이 조정"),
        ("+ 배속 추가",                 "speed",      True,  "구간 배속 — 기본 2.0× 5초"),
        ("+ 줌 추가 (Stage 6)",         "zoom",       False, "다음 단계에서 구현"),
        ("+ 곁들임 영상 추가 (Stage 7)", "broll",      False, "다음 단계에서 구현"),
    ]

    def _show_add_menu_at(self, ms: int) -> None:
        """어느 lane 의 우클릭이든 호출. 6항목 통합 메뉴 띄움.

        popup() 사용 (non-blocking) — exec() 는 modal 이라 단위 테스트가 hang.
        실제 사용엔 클릭 시 정상 동작 (action.triggered 가 emit 됨).
        """
        menu = QMenu(self)
        # 메뉴 닫힐 때 자동 삭제 — 매 우클릭마다 새 QMenu 가 self 의 자식으로 누적되는 것 방지.
        menu.setAttribute(Qt.WA_DeleteOnClose, True)
        for label, eff_type, enabled, tooltip in self._MENU_ITEMS:
            action = QAction(label, menu)
            action.setEnabled(enabled)
            if tooltip:
                action.setToolTip(tooltip)
            if enabled:
                action.triggered.connect(
                    lambda _checked=False, t=eff_type, m=ms: self.request_add.emit(t, m)
                )
            menu.addAction(action)
        menu.setToolTipsVisible(True)
        self._last_menu = menu
        menu.popup(QCursor.pos())
