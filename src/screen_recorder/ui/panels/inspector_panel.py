"""인스펙터 패널 — 우측 도크 컨테이너.

영상 탭이 효과를 선택하면 set_effect(effect) 로 알리고, 패널은 type 에 맞는
인스펙터 폼을 띄운다. Stage 2 에서는 등록된 폼이 없으므로 모두 EmptyInspector
로 fallback. Stage 3+ 가 register_inspector("caption", CaptionInspector) 형태로
폼을 등록하면 그때부터 type 별 폼이 표시됨.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from ...effects.model import Effect
from ..video.inspectors.base import InspectorBase
from ..video.inspectors.empty_inspector import EmptyInspector


class InspectorPanel(QWidget):
    """type → 인스펙터 클래스 매핑 + 현재 효과에 맞는 폼 표시."""

    effect_changed = Signal(object)   # Effect — 인스펙터에서 bubble
    effect_deleted = Signal(str)      # effect_id — 인스펙터의 삭제 버튼이 발화 시 bubble

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        self._inspector_classes: dict[str, type] = {}
        self._empty = EmptyInspector()
        self._stack.addWidget(self._empty)
        self._stack.setCurrentWidget(self._empty)
        self._current_inspector: QWidget = self._empty

    # ---------- public ----------
    def register_inspector(self, effect_type: str, cls: type) -> None:
        """효과 type 에 대한 인스펙터 클래스 등록 (Stage 3+ 가 호출)."""
        self._inspector_classes[effect_type] = cls

    def set_effect(self, effect: Optional[Effect]) -> None:
        """선택된 효과를 표시. None 이면 EmptyInspector."""
        if effect is None:
            self._show_empty()
            return
        cls = self._inspector_classes.get(effect.type)
        if cls is None:
            self._show_empty()
            return
        # 새 인스펙터 인스턴스 — 매번 새로 만들어 상태 누수 방지
        inspector = cls()
        if not isinstance(inspector, InspectorBase):
            self._show_empty()
            return
        inspector.set_effect(effect)
        inspector.effect_changed.connect(self.effect_changed.emit)
        # effect_deleted 시그널은 모든 인스펙터에 있는 건 아니므로(SpeedInspector 만)
        # hasattr 로 안전하게 연결.
        if hasattr(inspector, "effect_deleted"):
            inspector.effect_deleted.connect(self.effect_deleted.emit)
        self._swap_current(inspector)

    def current_inspector(self) -> QWidget:
        return self._current_inspector

    # ---------- internal ----------
    def _show_empty(self) -> None:
        self._swap_current(self._empty, keep_widget=True)

    def _swap_current(self, widget: QWidget, *, keep_widget: bool = False) -> None:
        """stack 의 현재 위젯을 교체. keep_widget=False 면 이전 위젯은 폐기."""
        previous = self._current_inspector
        if widget is previous:
            return
        if self._stack.indexOf(widget) == -1:
            self._stack.addWidget(widget)
        self._stack.setCurrentWidget(widget)
        self._current_inspector = widget
        # 이전 위젯 폐기 (단, EmptyInspector 는 재사용)
        if not keep_widget and previous is not self._empty:
            self._stack.removeWidget(previous)
            previous.deleteLater()
