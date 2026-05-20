"""SubtitleExportSettingsDialog — Whisper 모델 + 형식 (TXT/SRT) 선택.

2026-05-20 신규 (사용자 요청). 사용자 명시: "Whisper 로 새로 생성. txt 디폴트,
srt 도 고를 수 있게. 모델 고를 수 있게."
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QRadioButton, QVBoxLayout,
)

from ..agent.transcript import VALID_MODEL_SIZES, WHISPER_SIZE_MB
from ..encode.subtitle_export import SubtitleExportSettings


class SubtitleExportSettingsDialog(QDialog):
    """자막 export 설정 다이얼로그.

    `initial_model` — settings.whisper_model_size 같은 사용자 기본값을 받아 콤보의
    초기 선택값으로. 누락 시 'base'.
    """

    def __init__(self, *, initial_model: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("자막 내보내기")
        self.setModal(True)
        self.resize(420, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # ---- 형식 ----
        self.txt_radio = QRadioButton("TXT (텍스트만)")
        self.srt_radio = QRadioButton("SRT (시간 정보 포함)")
        self.txt_radio.setChecked(True)   # 사용자 명시 — 디폴트 TXT
        self._format_group = QButtonGroup(self)
        self._format_group.addButton(self.txt_radio)
        self._format_group.addButton(self.srt_radio)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(self.txt_radio)
        fmt_row.addWidget(self.srt_radio)
        fmt_row.addStretch(1)
        form.addRow("형식", fmt_row)

        # ---- Whisper 모델 ----
        self.model_combo = QComboBox()
        for size in VALID_MODEL_SIZES:
            mb = WHISPER_SIZE_MB.get(size, 0)
            label = f"{size}  (~{mb} MB)" if mb else size
            # itemText 와 비교할 수 있도록 *plain size* 만 보이게 — 콤보 표시는 size + 용량.
            self.model_combo.addItem(size)
            # 사용자 친화 hint 는 tooltip 으로.
            idx = self.model_combo.count() - 1
            self.model_combo.setItemData(idx, label, Qt.ToolTipRole)
        initial = initial_model if initial_model in VALID_MODEL_SIZES else "base"
        self.model_combo.setCurrentText(initial)
        form.addRow("Whisper 모델", self.model_combo)

        # ---- 안내 ----
        hint = QLabel(
            "처음 사용하는 모델은 다운로드가 필요합니다 "
            "(tiny: ~39MB ~ large-v3: ~1.5GB). 한 번 받으면 캐시됨."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        # 사이드카 옆 전사 캐시가 있으면 같은 모델 재요청 시 즉시 재사용.
        cache_hint = QLabel("같은 영상 + 같은 모델로 이전에 전사했다면 캐시 사용 (빠름).")
        cache_hint.setWordWrap(True)
        cache_hint.setStyleSheet("color: #888;")
        layout.addWidget(cache_hint)

        # ---- 버튼 ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.Ok).setText("내보내기")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------- API ----------
    def current_settings(self) -> SubtitleExportSettings:
        fmt = "txt" if self.txt_radio.isChecked() else "srt"
        return SubtitleExportSettings(
            format=fmt, model_size=self.model_combo.currentText(),
        )

    def suggested_extension(self) -> str:
        return ".txt" if self.txt_radio.isChecked() else ".srt"
