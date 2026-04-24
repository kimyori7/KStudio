"""상단 녹화 컨트롤바 — 대상 선택(3버튼) + 시작/일시정지/정지."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
)


_TARGETS = [
    ("fullscreen", "🖥 전체 화면"),
    ("window",     "🪟 특정 창"),
    ("region",     "▭ 지정 영역"),
]


class ControlBar(QWidget):
    start_clicked = Signal()
    stop_clicked = Signal()
    pause_clicked = Signal()
    target_changed = Signal(str)
    screenshot_clicked = Signal()  # 신규: 스크린샷 버튼 (영역 캡처)

    def __init__(self):
        super().__init__()
        self.setObjectName("ControlBar")
        self.setStyleSheet(
            "#ControlBar { background-color: #23262D; border-bottom: 1px solid #2A2D34; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        self.rec_label = QLabel("● REC")
        self.rec_label.setStyleSheet("color: #6A6E78; font-weight: bold; font-size: 11pt;")
        layout.addWidget(self.rec_label)

        layout.addWidget(QLabel("대상:"))

        # 3개 토글 버튼 — 하나만 선택됨
        self._target_buttons: dict[str, QPushButton] = {}
        self._target_group = QButtonGroup(self)
        self._target_group.setExclusive(True)
        for key, label in _TARGETS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setStyleSheet(
                "QPushButton { padding: 5px 14px; }"
                "QPushButton:checked { "
                "  background-color: #2D5DA8; "
                "  color: white; "
                "  font-weight: bold; "
                "  border: 1px solid #4FC3F7; "
                "}"
            )
            # 같은 버튼을 다시 눌러도 target_changed가 재발행되도록 clicked 사용
            btn.clicked.connect(lambda _chk, k=key: self._on_target_clicked(k))
            self._target_buttons[key] = btn
            self._target_group.addButton(btn)
            layout.addWidget(btn)

        self._target_buttons["fullscreen"].setChecked(True)
        self._current_target = "fullscreen"

        layout.addStretch(1)

        self.start_btn = QPushButton("⏺ 시작")
        self.start_btn.clicked.connect(self.start_clicked.emit)
        layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸ 일시정지")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.pause_btn.setEnabled(False)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("⏹ 정지")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)

        self.screenshot_btn = QPushButton("📸 스크린샷")
        self.screenshot_btn.setToolTip("영역 지정 캡처")
        self.screenshot_btn.clicked.connect(self.screenshot_clicked.emit)
        layout.addWidget(self.screenshot_btn)

    # ---------- 대상 선택 ----------

    def current_target(self) -> str:
        return self._current_target

    def set_target(self, key: str) -> None:
        if key in self._target_buttons:
            self._target_buttons[key].setChecked(True)
            self._current_target = key

    def _on_target_clicked(self, key: str) -> None:
        self._current_target = key
        # 같은 버튼을 다시 눌러도 체크 상태 유지
        self._target_buttons[key].setChecked(True)
        self.target_changed.emit(key)

    # ---------- 녹화 상태 ----------

    def set_recording(self, recording: bool) -> None:
        self.start_btn.setEnabled(not recording)
        self.pause_btn.setEnabled(recording)
        self.stop_btn.setEnabled(recording)
        # 녹화 중에는 대상 변경 막기
        for btn in self._target_buttons.values():
            btn.setEnabled(not recording)
        if recording:
            self.rec_label.setStyleSheet("color: #E53935; font-weight: bold; font-size: 11pt;")
        else:
            self.rec_label.setStyleSheet("color: #6A6E78; font-weight: bold; font-size: 11pt;")
