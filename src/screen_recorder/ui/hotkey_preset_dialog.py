"""첫 실행 단축키 프리셋 선택 다이얼로그.

사용자가 두 카드(윈도우 표준 / 곰·팟) 중 하나를 클릭하면 프리셋 적용 + 다이얼로그 종료.
"건너뛰기" 는 현재 settings 값을 유지하고 preset_name 을 'custom' 으로 마킹 (다음
실행부턴 노출 안 됨).
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


_CARD_STYLE = """
QFrame#presetCard {
    background-color: #2A2D34;
    border: 2px solid #3A3D44;
    border-radius: 8px;
    padding: 12px;
}
QFrame#presetCard:hover {
    border-color: #4A90E2;
    background-color: #2F3340;
}
"""


class _PresetCard(QFrame):
    clicked = Signal(str)

    def __init__(self, *, preset_id: str, title: str, lines: list[str]) -> None:
        super().__init__()
        self.setObjectName("presetCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(220)
        self.setMinimumHeight(180)
        self._preset_id = preset_id

        v = QVBoxLayout(self)
        v.setSpacing(6)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600; color: #E8E9EE;")
        v.addWidget(title_lbl)
        for line in lines:
            l = QLabel(line)
            l.setStyleSheet("color: #C0C4CC;")
            v.addWidget(l)
        v.addStretch(1)

    def mousePressEvent(self, _event):
        self.clicked.emit(self._preset_id)


class HotkeyPresetDialog(QDialog):
    """프리셋 카드 두 장 + 건너뛰기 버튼. 사용자가 고른 프리셋 이름은 selected_preset 속성."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("KStudio 단축키 프리셋 선택")
        self.setModal(True)
        self.resize(560, 320)
        self.selected_preset: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        intro = QLabel("자주 쓰는 단축키 묶음을 한 번에 적용합니다.\n"
                       "나중에 환경설정 → 단축키 에서 다시 바꿀 수 있습니다.")
        intro.setStyleSheet("color: #C0C4CC;")
        outer.addWidget(intro)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        outer.addLayout(cards_row, stretch=1)

        windows_card = _PresetCard(
            preset_id="windows-standard",
            title="🖥 윈도우 표준",
            lines=[
                "• 영역 캡처: Ctrl+Win+S",
                "• 영역 녹화: Ctrl+Alt+R",
                "• 트림: [ ] / Ctrl+E",
                "• 프레임: Ctrl+← / Ctrl+→",
            ],
        )
        windows_card.clicked.connect(self._on_card_clicked)
        cards_row.addWidget(windows_card)

        goompot_card = _PresetCard(
            preset_id="goom-pot",
            title="🎮 곰/팟 스타일",
            lines=[
                "• 영역 캡처: Ctrl+Shift+R",
                "• 영역 녹화: Ctrl+Shift+T",
                "• 트림: [ ] / Ctrl+E",
                "• 프레임: D / F",
            ],
        )
        goompot_card.clicked.connect(self._on_card_clicked)
        cards_row.addWidget(goompot_card)

        self.setStyleSheet(_CARD_STYLE)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        skip_btn = QPushButton("건너뛰기 (현재 키 유지)")
        skip_btn.clicked.connect(self._on_skip)
        bottom.addWidget(skip_btn)
        outer.addLayout(bottom)

    def _on_card_clicked(self, preset_id: str) -> None:
        self.selected_preset = preset_id
        self.accept()

    def _on_skip(self) -> None:
        self.selected_preset = None
        self.accept()
