"""글로벌 툴바 — 모드 토글 + 모드별 액션 (영상: 녹화 / 이미지: 캡처·저장·복사)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QFrame, QLabel, QButtonGroup,
)

from ..core.state import RecorderState
from .mode_controller import AppMode


_TARGETS = [("fullscreen", "🖥 전체화면"), ("window", "🪟 특정 창"), ("region", "▭ 지정 영역")]
_FORMATS = [("video", "영상"), ("gif", "GIF")]


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
    mode_value_changed = Signal(str)  # "video"/"gif" — 녹화 출력 형식

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

        # ---------- 모드 토글 (양쪽 공통) ----------
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self.video_btn = self._make_toggle_btn("🎞 영상", min_width=80)
        self.image_btn = self._make_toggle_btn("🖼 이미지", min_width=80)
        self._mode_group.addButton(self.video_btn)
        self._mode_group.addButton(self.image_btn)
        self.video_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.VIDEO))
        self.image_btn.clicked.connect(lambda: self.mode_clicked.emit(AppMode.IMAGE))
        layout.addWidget(self.video_btn)
        layout.addWidget(self.image_btn)
        self._sep1 = self._make_sep()
        layout.addWidget(self._sep1)

        # ---------- 영상 모드: 녹화 컨트롤 ----------
        self.record_btn = QPushButton("▶ 녹화")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("⏸ 일시정지")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("⏹ 정지")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        # ---------- 이미지 모드: 캡처 버튼 ----------
        self.capture_region_btn = QPushButton("📷 영역 캡처")
        self.capture_region_btn.clicked.connect(self.capture_region_clicked.emit)
        layout.addWidget(self.capture_region_btn)

        self.capture_full_btn = QPushButton("📷⛶ 전체 캡처")
        self.capture_full_btn.clicked.connect(self.capture_full_clicked.emit)
        layout.addWidget(self.capture_full_btn)

        self._sep2 = self._make_sep()
        layout.addWidget(self._sep2)

        # ---------- 영상 모드: 대상 토글 (전체화면/특정 창/지정 영역) ----------
        self._target_group = QButtonGroup(self)
        self._target_group.setExclusive(True)
        self._target_btns: dict[str, QPushButton] = {}
        for key, label in _TARGETS:
            btn = self._make_toggle_btn(label, min_width=70)
            self._target_btns[key] = btn
            self._target_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_target_btn_clicked(k))
            layout.addWidget(btn)
        # 기본 대상
        self._current_target_key = "fullscreen"
        self._target_btns["fullscreen"].setChecked(True)

        self._sep3 = self._make_sep()
        layout.addWidget(self._sep3)

        # ---------- 영상 모드: 모니터 (개수 가변이라 콤보 유지) ----------
        self._monitor_label = QLabel("모니터:")
        layout.addWidget(self._monitor_label)
        self.monitor_combo = QComboBox()
        self._refresh_monitors()
        self.monitor_combo.currentIndexChanged.connect(self.monitor_changed.emit)
        layout.addWidget(self.monitor_combo)

        self._sep4 = self._make_sep()
        layout.addWidget(self._sep4)

        # ---------- 영상 모드: 녹화 형식 토글 (영상/GIF) ----------
        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)
        self._format_btns: dict[str, QPushButton] = {}
        for key, label in _FORMATS:
            btn = self._make_toggle_btn(label, min_width=56)
            self._format_btns[key] = btn
            self._format_group.addButton(btn)
            btn.clicked.connect(lambda _chk=False, k=key: self._on_format_btn_clicked(k))
            layout.addWidget(btn)
        self._current_format_key = "video"
        self._format_btns["video"].setChecked(True)

        layout.addStretch(1)

        # ---------- 이미지 모드: 글로벌 액션 ----------
        self.save_btn = QPushButton("💾 저장")
        self.save_btn.clicked.connect(self.save_clicked.emit)
        layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("📋 복사")
        self.copy_btn.clicked.connect(self.copy_clicked.emit)
        layout.addWidget(self.copy_btn)

        # ---------- 양쪽 공통 ----------
        self.preferences_btn = QPushButton("⚙")
        self.preferences_btn.setFixedWidth(32)
        self.preferences_btn.setToolTip("환경설정 (Ctrl+,)")
        self.preferences_btn.clicked.connect(self.preferences_clicked.emit)
        layout.addWidget(self.preferences_btn)

        # 초기 상태
        self._current_mode: AppMode = AppMode.IMAGE
        self._current_state: RecorderState = RecorderState.IDLE
        self.set_mode(AppMode.IMAGE)
        self.set_recording_state(RecorderState.IDLE)

    # ---------- 외부 API ----------
    def set_mode(self, mode: AppMode) -> None:
        self._current_mode = mode
        if mode is AppMode.VIDEO:
            self.video_btn.setChecked(True)
        else:
            self.image_btn.setChecked(True)
        self._refresh_widgets_visibility()

    def set_recording_state(self, state: RecorderState) -> None:
        self._current_state = state
        self.pause_btn.setText("▶ 재개" if state == RecorderState.PAUSED else "⏸ 일시정지")
        # 녹화 중에는 옵션 잠금
        idle = state == RecorderState.IDLE
        for btn in self._target_btns.values():
            btn.setEnabled(idle)
        for btn in self._format_btns.values():
            btn.setEnabled(idle)
        self.monitor_combo.setEnabled(idle)
        self._refresh_widgets_visibility()

    def set_target(self, key: str) -> None:
        if key in self._target_btns and key != self._current_target_key:
            self._current_target_key = key
            self._target_btns[key].setChecked(True)

    def current_target(self) -> str:
        return self._current_target_key

    def set_recording_mode(self, key: str) -> None:
        if key in self._format_btns and key != self._current_format_key:
            self._current_format_key = key
            self._format_btns[key].setChecked(True)

    def current_recording_mode(self) -> str:
        return self._current_format_key

    def set_monitor_index(self, idx: int) -> None:
        if 0 <= idx < self.monitor_combo.count():
            self.monitor_combo.setCurrentIndex(idx)

    def current_monitor_index(self) -> int:
        return self.monitor_combo.currentIndex()

    # ---------- 가시성 통합 관리 ----------
    def _refresh_widgets_visibility(self) -> None:
        is_video = self._current_mode is AppMode.VIDEO
        is_image = not is_video
        state = self._current_state
        idle = state == RecorderState.IDLE
        active = state in (RecorderState.RECORDING, RecorderState.PAUSED)

        # 영상 모드 전용 — 녹화 컨트롤
        self.record_btn.setVisible(is_video and idle)
        self.pause_btn.setVisible(is_video and active)
        self.stop_btn.setVisible(is_video and active)

        # 영상 모드 전용 — 대상 토글, 모니터, 형식 토글
        for btn in self._target_btns.values():
            btn.setVisible(is_video)
        self._monitor_label.setVisible(is_video)
        self.monitor_combo.setVisible(is_video)
        for btn in self._format_btns.values():
            btn.setVisible(is_video)

        # 이미지 모드 전용 — 캡처 + 액션
        self.capture_region_btn.setVisible(is_image)
        self.capture_full_btn.setVisible(is_image)
        self.save_btn.setVisible(is_image)
        self.copy_btn.setVisible(is_image)

        # 분리자: 영상 모드에서만 의미 있는 것들
        self._sep2.setVisible(is_video)
        self._sep3.setVisible(is_video)
        self._sep4.setVisible(is_video)

    # ---------- 내부 ----------
    def _make_toggle_btn(self, text: str, *, min_width: int) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setMinimumWidth(min_width)
        return b

    def _make_sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setFixedWidth(2)
        f.setStyleSheet(
            "QFrame { background-color: #4A5060; border: none; "
            "margin-left: 6px; margin-right: 6px; }"
        )
        return f

    def _refresh_monitors(self) -> None:
        screens = QGuiApplication.screens() or []
        self.monitor_combo.clear()
        for i, s in enumerate(screens):
            g = s.geometry()
            self.monitor_combo.addItem(f"{i + 1}: {g.width()}×{g.height()}", i)
        if not screens:
            self.monitor_combo.addItem("1", 0)

    def _on_target_btn_clicked(self, key: str) -> None:
        if key == self._current_target_key:
            return
        self._current_target_key = key
        self.target_changed.emit(key)

    def _on_format_btn_clicked(self, key: str) -> None:
        if key == self._current_format_key:
            return
        self._current_format_key = key
        self.mode_value_changed.emit(key)
