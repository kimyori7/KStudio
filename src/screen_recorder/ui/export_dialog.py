"""ExportDialog — Sidecar export 진행 표시 (% + ETA) + 취소."""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)


def _format_eta(seconds: float) -> str:
    """ETA 초 → "1분 23초" 형식. 1시간 이상은 "1시간 5분", 음수/0 은 빈 문자열."""
    if seconds <= 0 or seconds > 86400:
        return ""
    total = int(round(seconds))
    if total < 60:
        return f"{total}초"
    minutes = total // 60
    secs = total % 60
    if minutes < 60:
        if secs == 0:
            return f"{minutes}분"
        return f"{minutes}분 {secs}초"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}시간 {minutes}분"


class ExportDialog(QDialog):
    cancel_requested = Signal()
    open_folder_requested = Signal(object)   # Path

    def __init__(self, *, total_duration_ms: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("영상 내보내기")
        self.setModal(True)
        self.resize(440, 170)
        self._total_ms = int(total_duration_ms)
        self._dst: Path | None = None
        # ETA 계산용 — 첫 progress signal 받은 시각부터 elapsed 측정.
        # ffmpeg 실행 자체 시작 시각이 아니라 첫 progress 가 더 정확 (인코딩 워밍업 제외).
        self._timer = QElapsedTimer()
        self._timer_started = False

        layout = QVBoxLayout(self)
        self.status_label = QLabel("내보내는 중…")
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)
        # ETA 표시 — progress 한 자릿수 이상부터 의미 있음.
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: #888;")
        layout.addWidget(self.eta_label)

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
        pct = max(0, min(100, int(pct)))
        self.progress_bar.setValue(pct)
        # ETA — 첫 progress 부터 측정. pct >= 1 부터 의미 있음 (0 으로 나눔 회피 + 노이즈).
        if not self._timer_started and pct > 0:
            self._timer.start()
            self._timer_started = True
            return
        if not self._timer_started or pct <= 0 or pct >= 100:
            return
        elapsed_s = self._timer.elapsed() / 1000.0
        # ETA = elapsed * (100 - pct) / pct — 선형 외삽 (단순화).
        eta_s = elapsed_s * (100 - pct) / pct
        eta_text = _format_eta(eta_s)
        if eta_text:
            self.eta_label.setText(f"예상 남은 시간: {eta_text}")

    def set_finished(self, dst: Path) -> None:
        self._dst = dst
        self.status_label.setText(f"완료: {dst.name}")
        self.progress_bar.setValue(100)
        elapsed_text = ""
        if self._timer_started:
            elapsed_s = self._timer.elapsed() / 1000.0
            elapsed_text = f" (소요 {_format_eta(elapsed_s)})"
        self.eta_label.setText(f"완료{elapsed_text}")
        self.cancel_btn.setVisible(False)
        self.open_folder_btn.setVisible(True)
        self.close_btn.setVisible(True)

    def set_error(self, msg: str) -> None:
        self.status_label.setText(f"실패: {msg}")
        self.eta_label.setText("")
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)

    def _on_open_folder(self) -> None:
        if self._dst is not None:
            self.open_folder_requested.emit(self._dst)
