"""공용 위젯 — 글로벌 툴바와 환경설정 다이얼로그가 공유."""
from __future__ import annotations

from PySide6.QtWidgets import QKeySequenceEdit, QWidget


class OneShotKeySequenceEdit(QKeySequenceEdit):
    """한 번 입력 후 자동으로 capture 를 끝내는 QKeySequenceEdit.

    기본 QKeySequenceEdit 는 setMaximumSequenceLength(1) 이어도 입력 후 포커스가
    유지돼, 사용자가 다음 키를 누르면 또다시 새 시퀀스가 잡혀 "여러번 먹는"
    것처럼 느껴진다. 이 서브클래스는 editingFinished 시 즉시 clearFocus() 를
    호출해 capture 를 닫고, 포커스 상태를 시각적으로 표시한다.
    """

    _STYLE_IDLE = (
        "QLineEdit { border: 1px solid #555; padding: 2px 4px; }"
    )
    _STYLE_CAPTURE = (
        "QLineEdit { border: 2px solid #E53935; background: #2A1E1E; "
        "color: #FFCDD2; padding: 1px 3px; }"
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumSequenceLength(1)
        self.setStyleSheet(self._STYLE_IDLE)
        # 한 번 입력되면 자동 종료 — clearFocus 하면 focusOutEvent 가 발화해 스타일 복귀.
        self.editingFinished.connect(self.clearFocus)

    def focusInEvent(self, e) -> None:  # type: ignore[override]
        super().focusInEvent(e)
        self.setStyleSheet(self._STYLE_CAPTURE)
        self.setToolTip("🔴 지정 중입니다 — 단축키 한 번만 누르세요.")

    def focusOutEvent(self, e) -> None:  # type: ignore[override]
        super().focusOutEvent(e)
        self.setStyleSheet(self._STYLE_IDLE)
        self.setToolTip("")
