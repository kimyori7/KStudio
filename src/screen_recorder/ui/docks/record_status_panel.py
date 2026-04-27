"""녹화 상태 패널."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ...core.state import RecorderState


_TARGET_LABELS = {
    "fullscreen": "전체화면",
    "window": "특정 창",
    "region": "지정 영역",
}


class RecordStatusPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        title = QLabel("🎬 녹화 상태")
        title.setStyleSheet("color: #A0A4AB; font-weight: bold;")
        layout.addWidget(title)

        self.state_label = QLabel("● 대기 중")
        layout.addWidget(self.state_label)

        self.target_label = QLabel("대상: 전체화면")
        self.mode_label = QLabel("모드: MP4")
        layout.addWidget(self.target_label)
        layout.addWidget(self.mode_label)

        layout.addStretch(1)

    def set_state(self, state: RecorderState) -> None:
        text = {
            RecorderState.IDLE: "● 대기 중",
            RecorderState.RECORDING: "● 녹화 중",
            RecorderState.PAUSED: "❚❚ 일시정지",
        }.get(state, "")
        color = {
            RecorderState.IDLE: "#6A6E78",
            RecorderState.RECORDING: "#E53935",
            RecorderState.PAUSED: "#FFA000",
        }.get(state, "#6A6E78")
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_target(self, key: str) -> None:
        self.target_label.setText(f"대상: {_TARGET_LABELS.get(key, key)}")

    def set_mode(self, mode: str) -> None:
        self.mode_label.setText(f"모드: {'MP4' if mode == 'video' else 'GIF'}")
