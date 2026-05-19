"""ExportDialog — Sidecar export 진행 표시 (% + ETA) + 취소.

ExportProgressOverlay — 메인 윈도우 오른쪽 하단에 붙는 소형 진행 위젯.
 · 스피너(회전 원호) + "내보내는 중… N%" + × 취소 버튼
 · 모달 없이 편집·이미지 모드 그대로 사용 가능.
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
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
        self.setModal(False)
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


class _Spinner(QWidget):
    """오른쪽 하단 진행 표시 — 회전 원호 애니메이션."""

    def __init__(self, size: int = 22, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start(40)   # ~25fps

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._angle = (self._angle + 15) % 360
        self.update()

    def paintEvent(self, event) -> None:   # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#3B82F6"), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        r = self.width() // 2 - 3
        cx, cy = self.width() // 2, self.height() // 2
        p.drawArc(cx - r, cy - r, 2 * r, 2 * r,
                  self._angle * 16, 270 * 16)


class ExportProgressOverlay(QWidget):
    """메인 윈도우 오른쪽 하단 소형 내보내기 진행 오버레이.

    · 스피너 + "내보내는 중… N%" + × 취소 버튼
    · ExportJob.progress / finished / error 시그널에 연결해 show/hide.
    · 부모(MainWindow) resizeEvent 후 reposition() 를 호출해 위치 고정.
    """

    cancel_clicked = Signal()

    _MARGIN = 12
    _BG = QColor(30, 30, 30, 220)
    _RADIUS = 8

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.Widget)
        self._pct = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self._spinner = _Spinner(parent=self)
        layout.addWidget(self._spinner)

        self._label = QLabel("내보내는 중… 0%")
        self._label.setStyleSheet("color: #fff; font-size: 12px;")
        layout.addWidget(self._label)

        self._cancel_btn = QPushButton("×")
        self._cancel_btn.setFixedSize(22, 22)
        self._cancel_btn.setStyleSheet(
            "QPushButton { color:#fff; background:#555; border-radius:11px; font-weight:bold; }"
            "QPushButton:hover { background:#888; }"
        )
        self._cancel_btn.setToolTip("내보내기 취소")
        self._cancel_btn.clicked.connect(self.cancel_clicked.emit)
        layout.addWidget(self._cancel_btn)

        self.adjustSize()
        self.hide()

    def paintEvent(self, event) -> None:   # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._BG)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), self._RADIUS, self._RADIUS)

    def set_progress(self, pct: int) -> None:
        self._pct = max(0, min(100, int(pct)))
        self._label.setText(f"내보내는 중… {self._pct}%")

    def set_finished(self, dst=None) -> None:
        self._spinner.stop()
        self._label.setText("내보내기 완료")
        self._cancel_btn.hide()
        QTimer.singleShot(3000, self.hide)

    def set_error(self, msg: str) -> None:
        self._spinner.stop()
        self._label.setText(f"내보내기 실패")
        self._cancel_btn.hide()
        QTimer.singleShot(4000, self.hide)

    def show_export(self) -> None:
        """내보내기 시작 시 호출."""
        self._pct = 0
        self._label.setText("내보내는 중… 0%")
        self._cancel_btn.show()
        self.adjustSize()
        self.reposition()
        self._spinner.start()
        self.show()
        self.raise_()

    def reposition(self) -> None:
        """부모 크기 변경 시마다 오른쪽 하단으로 재배치."""
        parent = self.parent()
        if parent is None:
            return
        pw, ph = parent.width(), parent.height()
        self.adjustSize()
        x = pw - self.width() - self._MARGIN
        y = ph - self.height() - self._MARGIN
        self.move(x, y)
