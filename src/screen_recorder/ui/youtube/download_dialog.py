"""영상 URL 가져오기 통합 팝업 — 영상/음악(mp3) 모드를 같은 다이얼로그로 처리한다.

메뉴 두 항목(영상 URL에서 가져오기 / URL에서 음악(mp3) 추출)이 mode 만 다르게 이 다이얼로그를
연다. 엔진(yt-dlp)은 유튜브 외 다수 사이트를 지원하므로 UI 는 특정 플랫폼을 앞세우지 않는다.
주소 + 저장 폴더(찾아보기, 기억) + 품질 드롭다운(모드별 항목)을 한 곳에 모으고, 하단에
"권리 있는 영상만" 안내문을 둔다(다운로드 책임은 사용자에게 있음을 명시).
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
        self.setWindowTitle("영상 URL에서 가져오기" if mode == "video" else "URL에서 음악(mp3) 추출")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("영상 주소(URL)"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("영상 페이지 주소를 붙여넣으세요")
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

        # 사용 책임 안내 — 다운로드는 중립적 도구이고, 받는 콘텐츠의 권리/약관 준수는
        # 사용자 책임임을 명시(특정 사이트를 지목하지 않음).
        notice = QLabel(
            "본인이 권리를 가졌거나 사용이 허락된 영상만 받으세요. "
            "각 사이트의 약관 준수는 사용자 책임입니다."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        layout.addWidget(notice)

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
