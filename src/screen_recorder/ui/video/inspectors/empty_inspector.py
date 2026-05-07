"""EmptyInspector — 효과 미선택 시 안내 라벨."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ....core.i18n import tr


class EmptyInspector(QWidget):
    """우측 도크 내부 인스펙터의 빈 상태.

    효과가 선택되지 않은 채로 편집 모드가 켜져 있을 때 보인다.
    """

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        layout.addStretch(1)
        self._label = QLabel(tr("효과를 선택하면 여기에 옵션이 표시됩니다."))
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: #888;")
        layout.addWidget(self._label)
        layout.addStretch(2)
