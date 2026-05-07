"""ExportDialog — Sidecar export 진행 표시 + 취소."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)


class ExportDialog(QDialog):
    cancel_requested = Signal()
    open_folder_requested = Signal(object)   # Path

    def __init__(self, *, total_duration_ms: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("영상 내보내기")
        self.setModal(True)
        self.resize(400, 140)
        self._total_ms = int(total_duration_ms)
        self._dst: Path | None = None

        layout = QVBoxLayout(self)
        self.status_label = QLabel("내보내는 중…")
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        self.open_folder_btn = QPushButton("폴더 열기")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.open_folder_btn)
        self.close_btn = QPushButton("닫기")
        self.close_btn.setVisible(False)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def set_progress(self, pct: int) -> None:
        self.progress_bar.setValue(max(0, min(100, int(pct))))

    def set_finished(self, dst: Path) -> None:
        self._dst = dst
        self.status_label.setText(f"완료: {dst.name}")
        self.progress_bar.setValue(100)
        self.cancel_btn.setVisible(False)
        self.open_folder_btn.setVisible(True)
        self.close_btn.setVisible(True)

    def set_error(self, msg: str) -> None:
        self.status_label.setText(f"실패: {msg}")
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)

    def _on_open_folder(self) -> None:
        if self._dst is not None:
            self.open_folder_requested.emit(self._dst)
