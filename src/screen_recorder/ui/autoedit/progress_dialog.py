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
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._label = QLabel(
            "준비 중...\n"
            "(첫 실행이면 Whisper 모델 다운로드 — 약 200MB, 1~5분 소요)"
        )
        self._label.setWordWrap(True)
        self._bar = QProgressBar()
        # 초기엔 indeterminate (다운로드 중 응답성 표시). 첫 진행률 emit 시 determinate 로 전환.
        self._bar.setRange(0, 0)
        self._cancel = QPushButton("취소")
        self._cancel.clicked.connect(self.cancelled.emit)

        lay = QVBoxLayout(self)
        lay.addWidget(self._label)
        lay.addWidget(self._bar)
        lay.addWidget(self._cancel)

    def update_progress(self, label: str, frac: float) -> None:
        self._label.setText(label)
        # 첫 진행률 emit 시 indeterminate(0/0) → determinate(0/100) 전환.
        if self._bar.maximum() == 0:
            self._bar.setRange(0, 100)
        self._bar.setValue(int(max(0.0, min(1.0, frac)) * 100))

    def set_phase_label(self, whisper_model: str, is_download: bool) -> None:
        """초기 라벨을 모델별 메시지로 — '다운로드 중' / '분석 중'.

        VideoTab._start_autoedit 가 모델 캐시 여부 확인 후 호출.
        """
        if is_download:
            self._label.setText(
                f"⬇ Whisper '{whisper_model}' 모델 다운로드 중...\n"
                f"(네트워크 속도에 따라 1~10분, 한 번만 받음)"
            )
        else:
            self._label.setText(f"분석 중... (Whisper '{whisper_model}')")

    def label(self) -> QLabel: return self._label
    def bar(self) -> QProgressBar: return self._bar
    def cancel_button(self) -> QPushButton: return self._cancel

    def reject(self) -> None:
        self.cancelled.emit()
        super().reject()
