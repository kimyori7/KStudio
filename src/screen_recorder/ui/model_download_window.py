"""ModelDownloadWindow — 모델 다운로드 진행률 비모달 별창.

SubtitleExportProgressWindow 와 같은 패턴. 닫기 = 숨김만 (백그라운드 다운로드 계속).

Phase 흐름:
- preparing: 다운로드 시작 직전 (디스크/캐시 확인 등).
- downloading: 실제 파일 받는 중 — bytes 진행률 표시.
- loading: 다운로드 끝, 모델을 메모리에 올리는 중.
- done: 완료.
- error: 실패.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


_PHASE_LABELS = {
    "preparing": "준비 중…",
    "downloading": "모델 다운로드 중",
    "loading": "모델 로딩 중",
    "done": "완료",
    "error": "오류",
}


class ModelDownloadWindow(QDialog):
    """모델 다운로드 진행률 별창 — 비모달, 닫아도 백그라운드 다운로드 계속."""

    closed = Signal()

    def __init__(
        self,
        repo_id: str,
        display_name: str,
        estimated_size_gb: float,
        parent=None,
    ) -> None:
        # 비모달 — 메인 윈도우 입력 안 막음. 별창 처럼 떠 있게.
        super().__init__(parent)
        self._repo_id = repo_id
        self._display_name = display_name
        self._estimated_size_gb = estimated_size_gb

        self.setWindowTitle(f"모델 다운로드 — {display_name}")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.resize(520, 360)

        layout = QVBoxLayout(self)

        # ---- 모델 이름 (헤더) ----
        title = QLabel(display_name)
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # ---- 안내 문구 ----
        info = QLabel(
            f"HuggingFace 에서 모델 다운로드 중. 예상 {estimated_size_gb:.1f} GB "
            f"— 인터넷 속도에 따라 소요 시간 달라짐. 창을 닫아도 백그라운드에서 계속됩니다."
        )
        info.setStyleSheet("color: #555; margin-bottom: 8px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # ---- Phase 라벨 ----
        self.phase_label = QLabel(_PHASE_LABELS["preparing"])
        self.phase_label.setStyleSheet("font-weight: bold; color: #2563eb;")
        layout.addWidget(self.phase_label)

        # ---- Progress bar + 텍스트 라벨 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel("0%")
        self.progress_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(self.progress_label)

        # ---- 로그 ----
        log_lbl = QLabel("로그:")
        log_lbl.setStyleSheet("margin-top: 6px;")
        layout.addWidget(log_lbl)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "font-family: 'Consolas','D2Coding',monospace; font-size: 11px;"
        )
        layout.addWidget(self.log_view, stretch=1)

        # ---- 버튼 row ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.close_btn = QPushButton("창 닫기 (백그라운드 계속)")
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    # ============================================================
    # 외부 API — 다운로드 잡이 호출
    # ============================================================
    def set_phase(self, phase: str) -> None:
        """phase 전환 — preparing / downloading / loading / done / error."""
        label = _PHASE_LABELS.get(phase, phase)
        self.phase_label.setText(label)
        if phase == "done":
            self.phase_label.setStyleSheet("font-weight: bold; color: #16a34a;")  # 초록
        elif phase == "error":
            self.phase_label.setStyleSheet("font-weight: bold; color: #dc2626;")  # 빨강
        else:
            self.phase_label.setStyleSheet("font-weight: bold; color: #2563eb;")  # 파랑

    def update_progress(self, received_bytes: int, total_bytes: int) -> None:
        """다운로드 progress 갱신 — bar + MB / % 라벨.

        시각 일관성 (2026-05-27 사용자 보고): 추정 estimated 보다 실제 received 가
        더 크면 (HF snapshot_download 가 모든 variant 받기 때문) 바는 100% 막대에
        도달했는데 라벨엔 "100% (27918 / 7106 MB)" 처럼 숫자가 어긋남.
        → received > total 이면 라벨도 "총량 미정" 모드로 전환.
        """
        if total_bytes > 0 and received_bytes <= total_bytes:
            pct = int(received_bytes / total_bytes * 100)
            pct = max(0, min(100, pct))
            self.progress_bar.setValue(pct)
            mb_recv = received_bytes / (1024 * 1024)
            mb_total = total_bytes / (1024 * 1024)
            self.progress_label.setText(f"{pct}% ({mb_recv:.1f} / {mb_total:.1f} MB)")
        else:
            # total 미상 OR 추정 초과 — 받은 양만 표시.
            mb_recv = received_bytes / (1024 * 1024)
            self.progress_bar.setRange(0, 0)   # 무한 막대로 전환
            if total_bytes > 0:
                mb_est = total_bytes / (1024 * 1024)
                self.progress_label.setText(
                    f"{mb_recv:.1f} MB 받음 (추정 {mb_est:.0f} MB 초과 — variant 다중 다운로드)"
                )
            else:
                self.progress_label.setText(f"{mb_recv:.1f} MB 받음 (전체 크기 미정)")

    def append_log(self, text: str) -> None:
        """로그 한 줄 추가 + 스크롤 맨 아래로."""
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self.log_view.insertPlainText(text + "\n")
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ============================================================
    # Qt 이벤트
    # ============================================================
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        # 닫기 = 숨김만 (Qt 의 close() 는 hide() 호출 — 부모가 destroy 안 하면 객체 살아 있음).
        # closed 시그널은 호출자가 hook 걸어 백그라운드 잡 유지 여부 판단할 수 있게.
        self.closed.emit()
        super().closeEvent(event)
