"""글로벌 툴바 — 모드 토글 + 녹화 컨트롤 + 옵션 + 글로벌 액션."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QFrame, QLabel, QButtonGroup,
)

from ..core.state import RecorderState
from .mode_controller import AppMode


_TARGETS = [("fullscreen", "🖥 전체화면"), ("window", "🪟 특정 창"), ("region", "▭ 지정 영역")]
_MODES = [("video", "영상"), ("gif", "GIF")]


class GlobalToolbar(QWidget):
    # 모드
    mode_clicked = Signal(object)  # AppMode

    # 녹화
    record_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    capture_region_clicked = Signal()
    capture_full_clicked = Signal()

    # 옵션
    target_changed = Signal(str)
    monitor_changed = Signal(int)
    mode_value_changed = Signal(str)  # "video"/"gif"

    # 액션
    save_clicked = Signal()
    copy_clicked = Signal()
    preferences_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("GlobalToolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # ---------- 모드 토글 ----------
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        self.video_btn = self._make_mode_btn("🎞 영상")
        self.image_btn = self._make_mode_btn("🖼 이미지")
        self._mode_group.addButton(self.video_btn)
        self._mode_group.addButton(self.image_btn)
        self.video_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.VIDEO))
        self.image_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.IMAGE))
        layout.addWidget(self.video_btn)
        layout.addWidget(self.image_btn)
        layout.addWidget(self._sep())

        # ---------- 녹화 컨트롤 ----------
        self.record_btn = QPushButton("▶ 녹화")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("⏸ 일시정지")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.pause_btn.setVisible(False)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("⏹ 정지")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.stop_btn.setVisible(False)
        layout.addWidget(self.stop_btn)

        self.capture_region_btn = QPushButton("📷 영역 캡처")
        self.capture_region_btn.clicked.connect(self.capture_region_clicked.emit)
        layout.addWidget(self.capture_region_btn)

        self.capture_full_btn = QPushButton("📷⛶ 전체 캡처")
        self.capture_full_btn.clicked.connect(self.capture_full_clicked.emit)
        layout.addWidget(self.capture_full_btn)

        layout.addWidget(self._sep())

        # ---------- 녹화 옵션 ----------
        layout.addWidget(QLabel("대상:"))
        self.target_combo = QComboBox()
        for key, label in _TARGETS:
            self.target_combo.addItem(label, key)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        layout.addWidget(self.target_combo)

        layout.addWidget(QLabel("모니터:"))
        self.monitor_combo = QComboBox()
        self._refresh_monitors()
        self.monitor_combo.currentIndexChanged.connect(self.monitor_changed.emit)
        layout.addWidget(self.monitor_combo)

        layout.addWidget(QLabel("모드:"))
        self.mode_combo = QComboBox()
        for key, label in _MODES:
            self.mode_combo.addItem(label, key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_value_changed)
        layout.addWidget(self.mode_combo)

        layout.addStretch(1)

        # ---------- 글로벌 액션 ----------
        self.save_btn = QPushButton("💾 저장")
        self.save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("📋 복사")
        self.copy_btn.clicked.connect(self.copy_clicked.emit)
        layout.addWidget(self.copy_btn)

        self.preferences_btn = QPushButton("⚙")
        self.preferences_btn.setFixedWidth(32)
        self.preferences_btn.setToolTip("환경설정 (Ctrl+,)")
        self.preferences_btn.clicked.connect(self.preferences_clicked.emit)
        layout.addWidget(self.preferences_btn)

        # 초기 상태
        self.set_mode(AppMode.IMAGE)
        self.set_recording_state(RecorderState.IDLE)

    # ---------- 외부 API ----------
    def set_mode(self, mode: AppMode) -> None:
        if mode is AppMode.VIDEO:
            self.video_btn.setChecked(True)
            self.save_btn.setVisible(False)
            self.copy_btn.setVisible(False)
        else:
            self.image_btn.setChecked(True)
            self.save_btn.setVisible(True)
            self.copy_btn.setVisible(True)

    def set_recording_state(self, state: RecorderState) -> None:
        idle = state == RecorderState.IDLE
        recording = state == RecorderState.RECORDING
        paused = state == RecorderState.PAUSED

        self.record_btn.setVisible(idle)
        self.pause_btn.setVisible(recording or paused)
        self.pause_btn.setText("▶ 재개" if paused else "⏸ 일시정지")
        self.stop_btn.setVisible(recording or paused)

        # 녹화 중에는 옵션 잠금
        for w in (self.target_combo, self.monitor_combo, self.mode_combo):
            w.setEnabled(idle)

    def set_target(self, key: str) -> None:
        for i in range(self.target_combo.count()):
            if self.target_combo.itemData(i) == key:
                self.target_combo.setCurrentIndex(i)
                return

    def current_target(self) -> str:
        return self.target_combo.currentData()

    def set_recording_mode(self, key: str) -> None:
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == key:
                self.mode_combo.setCurrentIndex(i)
                return

    def current_recording_mode(self) -> str:
        return self.mode_combo.currentData()

    def set_monitor_index(self, idx: int) -> None:
        if 0 <= idx < self.monitor_combo.count():
            self.monitor_combo.setCurrentIndex(idx)

    def current_monitor_index(self) -> int:
        return self.monitor_combo.currentIndex()

    # ---------- 내부 ----------
    def _make_mode_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setMinimumWidth(80)
        return b

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color: #3A3E47;")
        return f

    def _refresh_monitors(self) -> None:
        screens = QGuiApplication.screens() or []
        self.monitor_combo.clear()
        for i, s in enumerate(screens):
            g = s.geometry()
            self.monitor_combo.addItem(f"{i + 1}: {g.width()}×{g.height()}", i)
        if not screens:
            self.monitor_combo.addItem("1", 0)

    def _on_target_changed(self, _i: int) -> None:
        key = self.target_combo.currentData()
        if key:
            self.target_changed.emit(key)

    def _on_mode_value_changed(self, _i: int) -> None:
        key = self.mode_combo.currentData()
        if key:
            self.mode_value_changed.emit(key)
