"""상단 컨트롤바 — 녹화 섹션(대상/시작/일시정지/정지) + 스크린샷 섹션."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QButtonGroup, QFrame, QMenu,
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
    fullscreen_monitor_changed = Signal(int)  # 다중 모니터 환경에서 선택 변경

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
        self._fullscreen_monitor_index = 0
        self._refresh_fullscreen_label()

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

        # ---------- 녹화 | 스크린샷 구분선 ----------
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #3A3E47; background-color: #3A3E47; max-width: 1px;")
        sep.setFixedWidth(1)
        # 위아래로 약간의 숨 공간 — 라인이 너무 꽉 차 보이지 않게
        layout.addSpacing(6)
        layout.addWidget(sep)
        layout.addSpacing(6)

        # ---------- 스크린샷 섹션 (색상 차별화로 녹화와 구분) ----------
        self.screenshot_btn = QPushButton("📸 스크린샷")
        self.screenshot_btn.setToolTip("영역 지정 캡처")
        self.screenshot_btn.setStyleSheet(
            "QPushButton { "
            "  padding: 5px 14px; "
            "  background-color: #4A148C; "   # 짙은 보라 — REC 붉은 계열과 명확히 구분
            "  color: white; "
            "  font-weight: bold; "
            "  border: 1px solid #7B1FA2; "
            "  border-radius: 3px; "
            "}"
            "QPushButton:hover { background-color: #6A1B9A; }"
            "QPushButton:pressed { background-color: #38006B; }"
        )
        self.screenshot_btn.clicked.connect(self.screenshot_clicked.emit)
        layout.addWidget(self.screenshot_btn)

    # ---------- 대상 선택 ----------

    def current_target(self) -> str:
        return self._current_target

    def set_target(self, key: str) -> None:
        if key in self._target_buttons:
            self._target_buttons[key].setChecked(True)
            self._current_target = key
            if key == "fullscreen":
                self._refresh_fullscreen_label()

    def fullscreen_monitor_index(self) -> int:
        return self._fullscreen_monitor_index

    def set_fullscreen_monitor_index(self, idx: int) -> None:
        screens = QGuiApplication.screens()
        idx = max(0, min(idx, len(screens) - 1)) if screens else 0
        self._fullscreen_monitor_index = idx
        self._refresh_fullscreen_label()

    def _on_target_clicked(self, key: str) -> None:
        self._current_target = key
        self._target_buttons[key].setChecked(True)
        self.target_changed.emit(key)
        # 전체 화면이면서 모니터가 2개 이상이면 모니터 선택 메뉴를 이어서 띄움
        if key == "fullscreen" and len(QGuiApplication.screens()) >= 2:
            self._show_monitor_menu()

    def _show_monitor_menu(self) -> None:
        screens = QGuiApplication.screens()
        if len(screens) < 2:
            return
        btn = self._target_buttons["fullscreen"]
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        primary = QGuiApplication.primaryScreen()
        for i, s in enumerate(screens):
            g = s.geometry()
            suffix = " — 주" if s is primary else ""
            act = QAction(f"모니터 {i + 1}  {g.width()}×{g.height()}{suffix}", menu)
            act.setCheckable(True)
            act.setChecked(i == self._fullscreen_monitor_index)
            act.triggered.connect(lambda _=False, idx=i: self._on_monitor_picked(idx))
            group.addAction(act)
            menu.addAction(act)
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_monitor_picked(self, idx: int) -> None:
        self._fullscreen_monitor_index = idx
        self._refresh_fullscreen_label()
        self.fullscreen_monitor_changed.emit(idx)

    def _refresh_fullscreen_label(self) -> None:
        btn = self._target_buttons.get("fullscreen")
        if btn is None:
            return
        screens = QGuiApplication.screens()
        if len(screens) >= 2:
            btn.setText(f"🖥 모니터 {self._fullscreen_monitor_index + 1} ▾")
        else:
            btn.setText("🖥 전체 화면")

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
