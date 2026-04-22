"""하단 상태 표시."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class StatusBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.state_label = QLabel("● 대기 중")
        self.state_label.setStyleSheet("color: #666;")
        layout.addWidget(self.state_label)

        layout.addStretch(1)

        self.drop_label = QLabel("drop: 0")
        self.drop_label.setStyleSheet("color: #666;")
        layout.addWidget(self.drop_label)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._elapsed = 0
        self._recording = False

    def set_recording(self, on: bool) -> None:
        self._recording = on
        if on:
            self._elapsed = 0
            self._timer.start()
            self._refresh()
        else:
            self._timer.stop()
            self.state_label.setText("● 대기 중")
            self.state_label.setStyleSheet("color: #666;")

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._timer.stop()
            self.state_label.setText("⏸ 일시정지")
            self.state_label.setStyleSheet("color: #FFB300;")
        elif self._recording:
            self._timer.start()
            self._refresh()

    def set_drop_count(self, n: int) -> None:
        color = "#FFB300" if n > 100 else "#666"
        self.drop_label.setText(f"drop: {n}")
        self.drop_label.setStyleSheet(f"color: {color};")

    def _tick(self) -> None:
        self._elapsed += 1
        self._refresh()

    def _refresh(self) -> None:
        h, rem = divmod(self._elapsed, 3600)
        m, s = divmod(rem, 60)
        self.state_label.setText(f"● 녹화 중 {h:02d}:{m:02d}:{s:02d}")
        self.state_label.setStyleSheet("color: #E53935;")
