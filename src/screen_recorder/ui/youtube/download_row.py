"""DownloadRow — 다운로드 1건의 진행/완료/실패를 표시하는 한 줄 위젯."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Signal, QSize
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QProgressBar, QPushButton

from ..icons import load_icon


def _fmt_bytes(n) -> str:
    """바이트를 사람이 읽기 좋은 단위로 — B/KB/MB/GB."""
    n = float(n or 0)
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{int(n)}B"


def _fmt_speed(bps) -> str:
    return _fmt_bytes(bps) + "/s"


class DownloadRow(QWidget):
    cancel_requested = Signal()
    retry_requested = Signal()
    close_requested = Signal()

    def __init__(self, title: str = "다운로드 준비 중…", parent=None) -> None:
        super().__init__(parent)
        self._path = ""
        # 상태 표시용 누적값 — 진행률 막대는 시각(%)만, 텍스트는 받은량/총량·속도.
        self._terminal = False
        self._downloaded = 0
        self._total = 0
        self._speed = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)

        self.title_label = QLabel(title)
        self.title_label.setMinimumWidth(160)
        self.title_label.setMaximumWidth(280)
        layout.addWidget(self.title_label, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(180)
        # 막대 내장 % 텍스트는 끈다 — 옆 status_label 이 "23%"/"완료"/"실패" 등을 표시하므로
        # 켜두면 같은 숫자가 두 번 보인다(막대 안 + 라벨). 텍스트 단일 출처 = status_label.
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        # "3.2MB / 12.5MB · 2.3MB/s" 가 안 잘리도록 넉넉히.
        self.status_label.setMinimumWidth(170)
        layout.addWidget(self.status_label)

        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.cancel_requested)
        layout.addWidget(self.cancel_btn)

        self.open_btn = QPushButton("열기")
        self.open_btn.clicked.connect(self._open_file)
        self.open_btn.hide()
        layout.addWidget(self.open_btn)

        self.folder_btn = QPushButton("폴더 열기")
        self.folder_btn.clicked.connect(self._open_folder)
        self.folder_btn.hide()
        layout.addWidget(self.folder_btn)

        self.retry_btn = QPushButton("다시 시도")
        self.retry_btn.clicked.connect(self.retry_requested)
        self.retry_btn.hide()
        layout.addWidget(self.retry_btn)

        # 목록에서 지우기 — 텍스트 '✕' 글리프가 일부 폰트에서 안 보여 빈 버튼처럼 보이던
        # 문제(사용자 보고) → SVG 'x' 아이콘 사용.
        self.close_btn = QPushButton()
        self.close_btn.setIcon(load_icon("x", size=14))
        self.close_btn.setIconSize(QSize(14, 14))
        self.close_btn.setFixedWidth(30)
        self.close_btn.setToolTip("목록에서 지우기")
        self.close_btn.clicked.connect(self.close_requested)
        self.close_btn.hide()
        layout.addWidget(self.close_btn)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self.title_label.setToolTip(title)

    def on_progress(self, downloaded, total) -> None:
        if self._terminal:
            return
        self._downloaded = int(downloaded or 0)
        self._total = int(total or 0)
        if self._total > 0:
            self.progress_bar.setRange(0, 100)
            pct = max(0, min(100, int(self._downloaded * 100 / self._total)))
            self.progress_bar.setValue(pct)
        else:
            # 전체 크기 미정 → busy indicator (0,0).
            self.progress_bar.setRange(0, 0)
        self._render_status()

    def on_speed(self, speed) -> None:
        if self._terminal:
            return
        self._speed = float(speed) if speed else None
        self._render_status()

    def _render_status(self) -> None:
        # % 대신 받은량/총량 + 속도. 막대(시각적 %)는 별도로 채워진다.
        if self._total > 0:
            text = f"{_fmt_bytes(self._downloaded)} / {_fmt_bytes(self._total)}"
        else:
            text = _fmt_bytes(self._downloaded)
        if self._speed:
            text += f" · {_fmt_speed(self._speed)}"
        self.status_label.setText(text)

    def on_finished(self, path: str) -> None:
        self._terminal = True
        self._path = path
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText("완료")
        self.cancel_btn.hide()
        self.open_btn.show()
        self.folder_btn.show()
        self.close_btn.show()

    def on_error(self, msg: str) -> None:
        self._terminal = True
        self.progress_bar.setRange(0, 100)
        self.status_label.setText("실패")
        self.status_label.setToolTip(msg)
        self.cancel_btn.hide()
        self.retry_btn.show()
        self.close_btn.show()

    def on_cancelled(self) -> None:
        self._terminal = True
        self.status_label.setText("취소됨")
        self.cancel_btn.hide()
        self.close_btn.show()

    def _open_file(self) -> None:
        if self._path and Path(self._path).exists():
            os.startfile(self._path)  # type: ignore[attr-defined]

    def _open_folder(self) -> None:
        if self._path:
            folder = str(Path(self._path).parent)
            subprocess.Popen(["explorer", folder])
