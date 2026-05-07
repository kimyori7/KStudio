"""인스펙터 베이스 — 효과별 폼이 상속하는 공통 위젯."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....effects.model import Effect


class InspectorBase(QWidget):
    """효과별 인스펙터의 공통 base.

    자식 폼은 set_effect(effect) 에서 자기 위젯들을 그 효과 값으로 채우고,
    사용자가 위젯을 변경하면 새 effect 객체를 만들어 effect_changed 로 발화한다.
    Stage 2 의 기본 구현은 no-op (Stage 3+ 에서 캡션/배속/줌/B-roll 인스펙터가
    이 클래스를 상속한다).
    """

    effect_changed = Signal(object)   # Effect — 사용자가 폼 값을 바꿨을 때

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._effect: Optional[Effect] = None

    def current_effect(self) -> Optional[Effect]:
        return self._effect

    def set_effect(self, effect: Optional[Effect]) -> None:
        """효과 객체를 폼에 채워 넣는다. None 이면 빈 상태."""
        self._effect = effect
        # 자식 클래스가 override 해 폼 위젯을 갱신
