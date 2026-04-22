"""상단 녹화 컨트롤바."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QPushButton,
)


class ControlBar(QWidget):
    start_clicked = Signal()
    stop_clicked = Signal()
    pause_clicked = Signal()
    target_changed = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.rec_label = QLabel("● REC")
        self.rec_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self.rec_label)

        layout.addWidget(QLabel("대상:"))
        self.target_combo = QComboBox()
        self.target_combo.addItem("전체 화면", "fullscreen")
        self.target_combo.addItem("특정 창", "window")
        self.target_combo.addItem("지정 영역", "region")
        self.target_combo.activated.connect(
            lambda _: self.target_changed.emit(self.target_combo.currentData())
        )
        layout.addWidget(self.target_combo)

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

    def set_recording(self, recording: bool) -> None:
        self.start_btn.setEnabled(not recording)
        self.pause_btn.setEnabled(recording)
        self.stop_btn.setEnabled(recording)
        self.rec_label.setStyleSheet(
            "color: #E53935; font-weight: bold;" if recording else "color: #888; font-weight: bold;"
        )
