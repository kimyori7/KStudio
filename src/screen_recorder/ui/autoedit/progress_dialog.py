"""분석 진행률 modal — 진행 중 다른 UI 차단 + 취소 버튼."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget


class AutoEditProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("자동 편집 — 분석 중")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._label = QLabel("준비 중...")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._cancel = QPushButton("취소")
        self._cancel.clicked.connect(self.cancelled.emit)

        lay = QVBoxLayout(self)
        lay.addWidget(self._label)
        lay.addWidget(self._bar)
        lay.addWidget(self._cancel)

    def update_progress(self, label: str, frac: float) -> None:
        self._label.setText(label)
        self._bar.setValue(int(max(0.0, min(1.0, frac)) * 100))

    def label(self) -> QLabel: return self._label
    def bar(self) -> QProgressBar: return self._bar
    def cancel_button(self) -> QPushButton: return self._cancel

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
