"""유튜브 다운로드 통합 팝업 — 영상/mp3 모드를 같은 다이얼로그로 처리한다.

메뉴 두 항목(유튜브 영상 추출 / mp3 변환)이 mode 만 다르게 이 다이얼로그를 연다.
주소 + 저장 폴더(찾아보기, 기억) + 품질 드롭다운(모드별 항목)을 한 곳에 모은다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from PySide6.QtWidgets import (
    QDialog, QLineEdit, QComboBox, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFileDialog, QDialogButtonBox,
)

from ...youtube.request import DownloadRequest

_VIDEO_QUALITIES = [("최고 화질", "best"), ("1080p", "1080"), ("720p", "720"), ("480p", "480")]
_MP3_QUALITIES = [("320 kbps", "320"), ("256 kbps", "256"), ("192 kbps", "192")]


class YouTubeDownloadDialog(QDialog):
    def __init__(
        self,
        mode: Literal["video", "mp3"],
        start_dir: Path,
        start_quality: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self.setWindowTitle("유튜브 영상 추출" if mode == "video" else "유튜브 mp3 변환")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("유튜브 주소"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        layout.addWidget(self.url_edit)

        layout.addWidget(QLabel("저장 폴더"))
        row = QHBoxLayout()
        self.dir_edit = QLineEdit(str(start_dir))
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._on_browse)
        row.addWidget(self.dir_edit, stretch=1)
        row.addWidget(browse)
        layout.addLayout(row)

        layout.addWidget(QLabel("품질"))
        self.quality_combo = QComboBox()
        choices = _VIDEO_QUALITIES if mode == "video" else _MP3_QUALITIES
        for label, data in choices:
            self.quality_combo.addItem(label, data)
        idx = self.quality_combo.findData(start_quality)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        layout.addWidget(self.quality_combo)

        buttons = QDialogButtonBox()
        self._ok = buttons.addButton("받기", QDialogButtonBox.AcceptRole)
        buttons.addButton("취소", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.dir_edit.text())
        if chosen:
            self.dir_edit.setText(chosen)

    def _on_accept(self) -> None:
        if self.build_request() is None:
            return  # 검증 실패(빈 URL/폴더) 시 닫지 않음
        self.accept()

    def build_request(self) -> Optional[DownloadRequest]:
        url = self.url_edit.text().strip()
        out = self.dir_edit.text().strip()
        if not url or not out:
            return None
        return DownloadRequest(
            url=url,
            mode=self._mode,
            out_dir=Path(out),
            quality=self.quality_combo.currentData(),
        )

    def selected_dir(self) -> str:
        return self.dir_edit.text().strip()

    def selected_quality(self) -> str:
        return self.quality_combo.currentData()
