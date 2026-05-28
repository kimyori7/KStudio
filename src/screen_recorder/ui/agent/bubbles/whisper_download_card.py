"""Whisper 모델 다운로드 동의 카드 — chat_panel.py 에서 분리 (Task 7).

동작 변경 없음.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

# Whisper 모델 옵션 — (model_size, display_label, size_mb, description).
# _WhisperDownloadCard 의 유일한 사용자이므로 이 파일 안에 둠.
_WHISPER_MODEL_OPTIONS: list[tuple[str, str, int, str]] = [
    ("tiny",     "tiny",     39,   "가장 가벼움, 정확도 낮음"),
    ("base",     "base",     74,   "균형 — 한국어 권장"),
    ("small",    "small",    244,  "정확도 더 좋음"),
    ("medium",   "medium",   769,  "한국어 강함, 다소 느림"),
    ("large-v3", "large-v3", 1550, "최고 정확도, 매우 무거움"),
]


class WhisperDownloadCard(QFrame):
    """Whisper 모델 다운로드 동의 카드 — Claude 의 download_whisper_model 호출 시.

    카드에 모델 크기 드롭다운 — Claude 가 요청한 크기가 기본 선택. 사용자가 다른
    크기로 변경 가능. [✓ 다운로드] 클릭 시 *선택된 크기* 가 실제 다운로드 됨.
    Claude 권한 없이 사용자 클릭만 실제 트리거.
    """

    download_clicked = Signal(str)    # 선택된 model_size 전달.
    cancel_clicked = Signal()

    def __init__(
        self,
        requested_size: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background:#1a1530;color:#ddd6fe;border:1px solid #a78bfa;"
            "border-radius:8px;padding:10px 12px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        title = QLabel("📥 Whisper 자막 모델 다운로드")
        title.setStyleSheet("color:#c4b5fd;font-weight:bold;font-size:13px;")
        title.setWordWrap(True)
        lay.addWidget(title)

        info = QLabel(
            "Claude 가 영상 자막 추출을 위해 모델 다운로드를 요청합니다. "
            "원하는 크기를 골라주세요 — 작을수록 빠르지만 정확도 낮음, "
            "클수록 정확하지만 디스크/메모리 더 씀. 한 번 받으면 재사용."
        )
        info.setStyleSheet("color:#ddd6fe;font-size:11px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        size_label = QLabel("모델 크기:")
        size_label.setStyleSheet("color:#c4b5fd;font-size:11px;")
        self._size_combo = QComboBox()
        for model_size, display, mb, desc in _WHISPER_MODEL_OPTIONS:
            self._size_combo.addItem(
                f"{display} (~{mb}MB — {desc})", userData=model_size,
            )
        # Claude 가 요청한 크기를 기본 선택.
        for i, (ms, _, _, _) in enumerate(_WHISPER_MODEL_OPTIONS):
            if ms == requested_size:
                self._size_combo.setCurrentIndex(i)
                break
        self._size_combo.setStyleSheet(
            "QComboBox{background:#1e1b4b;color:#ddd6fe;border:1px solid #a78bfa;"
            "border-radius:6px;padding:3px 8px;font-size:11px;}"
        )
        size_row.addWidget(size_label)
        size_row.addWidget(self._size_combo, 1)
        lay.addLayout(size_row)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#a5b4fc;font-size:11px;font-style:italic;")
        self._status.setVisible(False)
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._dl_btn = QPushButton("✓ 다운로드")
        self._dl_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:white;border:none;border-radius:6px;padding:6px 14px;font-weight:bold;}"
            "QPushButton:hover{background:#6d28d9;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._dl_btn.clicked.connect(self._on_download)
        self._cancel_btn = QPushButton("✗ 취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;border-radius:6px;padding:6px 14px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._dl_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._decided = False

    def _on_download(self) -> None:
        if self._decided:
            return
        self._decided = True
        chosen = self._size_combo.currentData() or "base"
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        self._status.setText(f"⏳ '{chosen}' 다운로드 중… (네트워크 속도에 따라 수 초~수 분)")
        self._status.setVisible(True)
        self.download_clicked.emit(str(chosen))

    def _on_cancel(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        self.cancel_clicked.emit()

    def mark_resolved(self, outcome: str, message: str = "") -> None:
        self._decided = True
        self._dl_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._size_combo.setEnabled(False)
        if outcome == "done":
            self._dl_btn.setText("✓ 다운로드 완료")
            self._status.setText(message or "디스크에 저장됨.")
            self._status.setVisible(True)
        elif outcome == "failed":
            self._dl_btn.setText("✗ 실패")
            self._status.setText(f"다운로드 실패: {message}")
            self._status.setVisible(True)
        elif outcome == "canceled":
            self._cancel_btn.setText("✗ 취소됨")
