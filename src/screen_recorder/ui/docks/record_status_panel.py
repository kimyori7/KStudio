"""녹화 상태 패널.

상단: 현재 녹화 상태/대상/모드 라벨.
하단: 환경설정에 있는 영상·사운드·GIF 설정을 그대로 임베드 — 매번 환경설정
다이얼로그를 열지 않고 도크 안에서 코덱/FPS/비트레이트 등을 즉시 바꿀 수 있다.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea,
)

from ...core.state import RecorderState
from ...core.settings import VideoSettings, GifSettings, SoundSettings
from ..panels.video_panel import VideoPanel


_TARGET_LABELS = {
    "fullscreen": "전체화면",
    "window": "특정 창",
    "region": "지정 영역",
}


class RecordStatusPanel(QWidget):
    # VideoPanel(영상/GIF/사운드) 의 settings_changed 를 그대로 외부에 전달.
    # main_window 가 받아 _persist_settings 호출.
    settings_changed = Signal()

    def __init__(
        self,
        video: VideoSettings | None = None,
        gif: GifSettings | None = None,
        sound: SoundSettings | None = None,
    ) -> None:
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

        # 분리선
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #3A3F4B; margin-top: 6px; margin-bottom: 4px;")
        layout.addWidget(sep)

        # 하단 — 영상/사운드/GIF 인라인 옵션 (settings 없이 만들면 생략)
        self.video_panel: VideoPanel | None = None
        if video is not None and gif is not None and sound is not None:
            # 도크 폭이 좁을 수 있어 스크롤 영역에 감싼다.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            self.video_panel = VideoPanel(video, gif, sound)
            scroll.setWidget(self.video_panel)
            layout.addWidget(scroll, stretch=1)
            self.video_panel.settings_changed.connect(self.settings_changed.emit)
        else:
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

    def refresh_from_settings(self) -> None:
        """환경설정 다이얼로그가 닫힌 직후처럼 외부에서 settings dataclass 가 바뀐 경우
        도크 위젯도 그 값을 다시 반영하도록 호출."""
        if self.video_panel is not None:
            self.video_panel.refresh_from_settings()
