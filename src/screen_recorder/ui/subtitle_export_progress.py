"""SubtitleExportProgressWindow — 자막 export 진행 + 실시간 자막 표시 (별창).

2026-05-20 사용자 요청: "추가 창에서 나오게 해서 어플은 병행으로 쓸수 있어야해."

비모달 (modal=False) — 메인 윈도우 작동 안 막음. 사용자가 닫기 눌러도 job 은
백그라운드 계속. finished 시점에 결과 파일 위치 표시 + '폴더 열기' 활성.

Phase 흐름:
- downloading: 다운로드 progress (받은 MB / 전체 MB) + spinner 메시지
- transcribing: 전사 progress (영상 길이 대비 %) + 실시간 자막 누적
- writing: 잠시 표시 후 finished
- finished: "완료" + 폴더 열기 버튼
- error: 빨간 메시지

SubtitleExportJob 의 시그널 4개 (download_progress, transcribe_progress,
segment_ready, phase_changed) + finished/error 를 모두 받아 UI 갱신.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)


_PHASE_LABEL = {
    "downloading": "모델 다운로드 중…",
    "loading": "모델 로딩 중…",
    "transcribing": "전사 중…",
    "writing": "파일 저장 중…",
}


def _format_mb(bytes_: int) -> str:
    return f"{bytes_ / (1024 * 1024):.1f} MB"


def _format_timecode(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class SubtitleExportProgressWindow(QDialog):
    """자막 export 진행 별창 — 비모달, 백그라운드 계속 가능."""

    # 사용자가 '폴더 열기' 누름 — main_window 가 받아 explorer 열기.
    open_folder_requested = Signal(object)   # Path
    # 2026-05-20: 사용자가 CPU 모드 라벨 옆 'GPU 활성화…' 누름 — GpuInstallDialog 열기.
    gpu_install_requested = Signal()

    def __init__(self, *, model_size: str, parent=None) -> None:
        # 비모달 — parent 가 메인 윈도우면 above 에 떠 있지만 입력 안 막음.
        super().__init__(parent)
        self.setWindowTitle(f"자막 내보내기 — {model_size}")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)   # 별창으로 (dialog 가 아닌 일반 윈도우 처럼).
        self.resize(520, 420)

        self._dst_path: Optional[Path] = None
        self._is_finished: bool = False

        layout = QVBoxLayout(self)

        # ---- Phase 라벨 + 보조 텍스트 (받은 MB 등) ----
        self.phase_label = QLabel("준비 중…")
        self.phase_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.phase_label)

        # 디바이스 표시 — 첫 segment 도착 시점에 "GPU (float16)" / "CPU (int8)" 갱신.
        # CPU 모드면 옆에 'GPU 활성화…' 버튼 노출 — 사용자가 메뉴 안 찾아도 됨.
        device_row = QHBoxLayout()
        device_row.setContentsMargins(0, 0, 0, 0)
        self.device_label = QLabel("디바이스: 확인 중…")
        self.device_label.setStyleSheet("color: #2563eb; font-size: 11px;")
        device_row.addWidget(self.device_label)
        self.gpu_install_btn = QPushButton("GPU 활성화…")
        self.gpu_install_btn.setStyleSheet(
            "font-size: 11px; padding: 1px 8px; color: #d97706;"
        )
        self.gpu_install_btn.setToolTip(
            "NVIDIA cuBLAS/cuDNN 라이브러리를 설치해 다음 자막 export 부터 GPU 가속 사용"
        )
        self.gpu_install_btn.clicked.connect(self.gpu_install_requested.emit)
        self.gpu_install_btn.hide()   # 초기엔 숨김 — device_info 받으면 결정.
        device_row.addWidget(self.gpu_install_btn)
        device_row.addStretch(1)
        layout.addLayout(device_row)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #888;")
        layout.addWidget(self.detail_label)

        # ---- Progress bar ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        # ---- 실시간 자막 ----
        captions_label = QLabel("실시간 자막:")
        captions_label.setStyleSheet("margin-top: 8px;")
        layout.addWidget(captions_label)

        self.captions_view = QTextEdit()
        self.captions_view.setReadOnly(True)
        self.captions_view.setStyleSheet("font-family: 'Pretendard', 'Malgun Gothic', sans-serif;")
        self.captions_view.setPlaceholderText("(전사가 시작되면 여기에 표시됩니다)")
        layout.addWidget(self.captions_view, stretch=1)

        # ---- 버튼 row ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.open_folder_btn = QPushButton("결과 폴더 열기")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self.open_folder_btn)
        self.close_btn = QPushButton("닫기")
        self.close_btn.clicked.connect(self.close)   # 비모달 — 닫아도 job 백그라운드 계속
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    # ============================================================
    # SubtitleExportJob 시그널 슬롯
    # ============================================================
    def on_phase_changed(self, phase: str) -> None:
        label = _PHASE_LABEL.get(phase, phase)
        self.phase_label.setText(label)
        if phase == "downloading":
            self.detail_label.setText("처음 사용하는 모델은 첫 다운로드가 필요합니다.")
            self.progress_bar.setValue(0)
        elif phase == "loading":
            self.detail_label.setText("모델을 메모리에 적재 중…")
            self.progress_bar.setRange(0, 0)   # indeterminate spinner (잠깐만).
        elif phase == "transcribing":
            self.detail_label.setText("영상의 음성을 자막으로 변환 중…")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        elif phase == "writing":
            self.detail_label.setText("파일 저장 중…")
            self.progress_bar.setValue(100)

    def on_download_progress(self, received_bytes: int, total_bytes: int) -> None:
        if total_bytes <= 0:
            self.detail_label.setText(f"받는 중… {_format_mb(received_bytes)}")
            return
        pct = int(min(100.0, received_bytes / total_bytes * 100.0))
        self.progress_bar.setValue(pct)
        self.detail_label.setText(
            f"{_format_mb(received_bytes)} / {_format_mb(total_bytes)}  ({pct}%)"
        )

    def on_device_info(self, info: str) -> None:
        """SubtitleExportJob.device_info — 'GPU (float16)' / 'CPU (int8)' 등.

        GPU 모드면 인라인 'GPU 활성화…' 버튼 숨김. CPU 모드면 노출 (사용자가
        다음 export 부터 GPU 쓰려면 라이브러리 설치).
        """
        self.device_label.setText(f"디바이스: {info}")
        is_gpu = info.lower().startswith("gpu")
        if is_gpu:
            self.device_label.setStyleSheet("color: #16a34a; font-size: 11px;")   # 초록
            self.gpu_install_btn.hide()
        else:
            self.device_label.setStyleSheet("color: #d97706; font-size: 11px;")   # 주황
            # gpu_acceleration_status() 가 'no_gpu' 면 버튼 무의미 — 호출자(main_window)가
            # 환경 보고 버튼 활성 여부 별도 제어 가능하지만, 일단 보여주고 클릭 시 안내.
            self.gpu_install_btn.show()

    def on_transcribe_progress(self, percent: int) -> None:
        self.progress_bar.setValue(int(max(0, min(100, percent))))

    def on_segment_ready(self, start_ms: int, end_ms: int, text: str) -> None:
        """전사된 segment 한 줄을 실시간 추가. 짧은 timecode + 본문."""
        line = f"[{_format_timecode(start_ms)}] {text}"
        # QTextEdit append — auto-scroll to bottom by default with cursor 위치.
        self.captions_view.append(line)
        # 스크롤 항상 맨 아래로 (사용자가 따라가게).
        cursor = self.captions_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.captions_view.setTextCursor(cursor)

    def on_finished(self, dst_path) -> None:
        self._is_finished = True
        self._dst_path = Path(dst_path)
        self.phase_label.setText("완료")
        self.detail_label.setText(f"저장됨: {self._dst_path.name}")
        self.detail_label.setStyleSheet("color: #16a34a;")   # 초록
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.open_folder_btn.setEnabled(True)

    def on_error(self, message: str) -> None:
        self._is_finished = True
        self.phase_label.setText("실패")
        self.detail_label.setText(message)
        self.detail_label.setStyleSheet("color: #dc2626;")   # 빨강
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    # ============================================================
    # 내부
    # ============================================================
    def _on_open_folder(self) -> None:
        if self._dst_path is not None:
            self.open_folder_requested.emit(self._dst_path)


def wire_job_to_window(job, window: SubtitleExportProgressWindow,
                          open_folder_cb: Optional[Callable] = None,
                          gpu_install_cb: Optional[Callable] = None) -> None:
    """job 의 시그널 6개 + finished/error 를 window 슬롯에 연결.

    main_window 의 _on_export_subtitle 에서 한 줄로 wiring 가능 — 시그널 + 폴더 열기
    + GPU 활성화 콜백.
    """
    job.phase_changed.connect(window.on_phase_changed)
    job.download_progress.connect(window.on_download_progress)
    job.transcribe_progress.connect(window.on_transcribe_progress)
    job.segment_ready.connect(window.on_segment_ready)
    job.device_info.connect(window.on_device_info)
    job.finished.connect(window.on_finished)
    job.error.connect(window.on_error)
    if open_folder_cb is not None:
        window.open_folder_requested.connect(open_folder_cb)
    if gpu_install_cb is not None:
        window.gpu_install_requested.connect(gpu_install_cb)
