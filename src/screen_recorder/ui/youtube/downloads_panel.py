"""DownloadsPanel — 메인 창 하단 고정 띠. 다운로드 작업들을 줄로 쌓아 보여준다.

QDockWidget 이 아니라 중앙 레이아웃에 삽입하는 일반 위젯이다 (전역 — 이미지/영상/
문서 모든 모드에서 동일하게 보여야 하므로, 모드별 dock 상태 직렬화/복원 기계장치를
건드리지 않으려고 dock 을 쓰지 않는다). 작업이 0개면 자동 숨김.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from .download_row import DownloadRow


class DownloadsPanel(QWidget):
    # 줄 수가 바뀔 때마다 방출 — 트레이 버튼이 자신의 표시/숨김을 결정하는 데 쓴다.
    rows_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[DownloadRow] = []
        self.setMaximumHeight(160)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QLabel("다운로드")
        self._header.setContentsMargins(8, 2, 8, 2)
        outer.addWidget(self._header)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        outer.addLayout(self._rows_layout)

        self.hide()

    def row_count(self) -> int:
        return len(self._rows)

    def set_header_text(self, text: str) -> None:
        """헤더 라벨 갱신 — 트레이 버튼이 '받는 중 N · 완료 누적 M' 요약을 넣는다."""
        self._header.setText(text)

    def add_job(self, job, title_hint: str = "다운로드 준비 중…") -> DownloadRow:
        row = DownloadRow(title=title_hint)
        self._rows.append(row)
        self._rows_layout.addWidget(row)

        job.progress.connect(row.on_progress)
        job.speed.connect(row.on_speed)
        job.title_resolved.connect(row.set_title)
        job.finished.connect(row.on_finished)
        job.error.connect(row.on_error)
        job.cancelled.connect(row.on_cancelled)
        row.cancel_requested.connect(job.cancel)
        row.close_requested.connect(lambda: self._remove_row(row))

        self._update_visibility()
        return row

    def _remove_row(self, row: DownloadRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        self._update_visibility()

    def _update_visibility(self) -> None:
        self.setVisible(len(self._rows) > 0)
        self.rows_changed.emit(len(self._rows))
