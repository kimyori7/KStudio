"""GPU 가속 1-클릭 설치 다이얼로그.

2026-05-20 사용자 요청: "저거(cuBLAS/cuDNN) 안 깔아도 되게 할 수는 없는거고?"
ctranslate2/faster-whisper 는 NVIDIA 런타임 DLL 이 디스크에 있어야 GPU 사용 가능.
직접 명령 안 치게 KStudio 가 venv 안에 pip 로 자동 설치.

흐름:
1. 사용자 확인 — "약 1.5GB 를 다운로드합니다. 계속하시겠어요?"
2. QProcess 로 `<venv-python> -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
3. pip 출력을 QTextEdit 에 실시간 표시 (진행 단계 가시화).
4. 완료 시 — 재시작 안내 (모듈 import 후 add_dll_directory 효과 제한).
5. 실패 시 — 빨간 에러 + 닫기.
"""
from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
)

from ..agent.transcript import NVIDIA_PIP_PACKAGES


class GpuInstallDialog(QDialog):
    """GPU 가속용 NVIDIA pip 패키지 설치 별창.

    - 비모달 (사용자가 다른 작업 병행 가능 — 자막 export 와 같은 패턴).
    - 닫기 버튼 = 다이얼로그 숨김만 (이미 시작한 pip 는 백그라운드 계속).
    - finished_ok 시그널 — 설치 성공 시 emit. main_window 가 재시작 안내 모달.
    """

    finished_ok = Signal()    # 설치 성공
    finished_error = Signal(str)   # 설치 실패 (메시지)

    def __init__(
        self,
        parent=None,
        packages: tuple[str, ...] | None = None,
        title: str | None = None,
        info_text: str | None = None,
    ) -> None:
        super().__init__(parent)
        # 기본값 = 기존 cuBLAS/cuDNN 동작 (호환성 100%).
        # packages 인자로 PyTorch 등 다른 패키지 세트도 동일 UI 로 설치 가능.
        self._packages = list(packages) if packages else list(NVIDIA_PIP_PACKAGES)

        self.setWindowTitle(title or "GPU 가속 활성화")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.resize(560, 440)

        self._process: Optional[QProcess] = None
        self._finished_emitted = False

        layout = QVBoxLayout(self)

        self.title_label = QLabel(title or "자막 내보내기 GPU 가속")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self.title_label)

        default_info = (
            "NVIDIA cuBLAS / cuDNN 라이브러리를 venv 안에 설치합니다.\n"
            "약 1.5GB 다운로드 — 인터넷 속도에 따라 수 분 ~ 십수 분 소요.\n"
            "설치 후 KStudio 를 재시작하면 large-v3 같은 큰 모델이 GPU 에서 빠르게 동작."
        )
        self.info_label = QLabel(info_text or default_info)
        self.info_label.setStyleSheet("color: #555; margin-bottom: 8px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.status_label = QLabel("대기 중…")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        log_label = QLabel("설치 로그:")
        log_label.setStyleSheet("margin-top: 6px;")
        layout.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "font-family: 'Consolas', 'D2Coding', monospace; font-size: 11px;"
        )
        self.log_view.setPlaceholderText("(설치 시작 시 pip 출력이 여기 표시됩니다)")
        layout.addWidget(self.log_view, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.install_btn = QPushButton("설치 시작")
        self.install_btn.clicked.connect(self._on_install_clicked)
        btn_row.addWidget(self.install_btn)
        self.close_btn = QPushButton("닫기")
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    # ============================================================
    # 설치 트리거
    # ============================================================
    def _on_install_clicked(self) -> None:
        if self._process is not None:
            return   # 이미 진행 중
        self.install_btn.setEnabled(False)
        self.status_label.setText("설치 중…")
        self.status_label.setStyleSheet("font-weight: bold; color: #2563eb;")

        self._process = QProcess(self)
        # stderr 도 stdout 채널로 합쳐 한 로그 뷰에 — pip 가 progress 를 stderr 로
        # 내보내는 경우 (download bar 등) 도 보임.
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels,
        )
        # 버퍼링 해제 env — pip 출력이 block-buffered 로 묶여 안 보이는 케이스 차단.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        self._process.setProcessEnvironment(env)

        self._process.started.connect(self._on_started)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)

        program = sys.executable
        # -u: 파이썬 자체 unbuffered. --no-input: stdin 안 막힘. --disable-pip-version-check:
        # 시작 지연 단축. --progress-bar off: pip progress bar (TTY 의존) 대신 단순 라인 출력.
        args = [
            "-u", "-m", "pip", "install",
            "--no-input", "--disable-pip-version-check",
            "--progress-bar", "off",
            "--upgrade", *self._packages,
        ]
        self._append_log(f"$ {program} {' '.join(args)}\n")
        self._append_log("(pip 응답 대기 중… 첫 출력까지 몇 초 걸릴 수 있습니다)\n")
        self._process.start(program, args)

    def _on_started(self) -> None:
        self._append_log("[프로세스 시작됨]\n")

    # ============================================================
    # QProcess 슬롯
    # ============================================================
    def _on_stdout(self) -> None:
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8", errors="replace",
        )
        if data:
            self._append_log(data)

    def _on_stderr(self) -> None:
        """MergedChannels 가 동작하지 않는 환경 안전망 — stderr 도 받아 표시."""
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardError()).decode(
            "utf-8", errors="replace",
        )
        if data:
            self._append_log(data)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        if exit_code == 0:
            self.status_label.setText("설치 완료 — KStudio 재시작 후 GPU 활성화됩니다.")
            self.status_label.setStyleSheet("font-weight: bold; color: #16a34a;")
            self._append_log("\n=== 설치 성공 ===\n")
            if not self._finished_emitted:
                self._finished_emitted = True
                self.finished_ok.emit()
        else:
            msg = f"pip 종료 코드 {exit_code}"
            self.status_label.setText(f"설치 실패 — {msg}")
            self.status_label.setStyleSheet("font-weight: bold; color: #dc2626;")
            self._append_log(f"\n=== 설치 실패 (exit {exit_code}) ===\n")
            if not self._finished_emitted:
                self._finished_emitted = True
                self.finished_error.emit(msg)
        self.install_btn.setEnabled(False)   # 한 번 돌리면 끝.

    def _on_error(self, err) -> None:
        # FailedToStart 등 — finished 가 호출 안 될 수도.
        name = getattr(err, "name", None) or str(err)
        program = sys.executable
        msg = (f"프로세스 오류: {name}\n"
               f"  python: {program}\n"
               f"  (이 경로의 python.exe 가 venv 가 아니거나 실행 권한 없으면 실패)")
        self.status_label.setText(f"프로세스 오류: {name}")
        self.status_label.setStyleSheet("font-weight: bold; color: #dc2626;")
        self._append_log(f"\n=== {msg} ===\n")
        if not self._finished_emitted:
            self._finished_emitted = True
            self.finished_error.emit(name)

    def _append_log(self, text: str) -> None:
        self.log_view.moveCursor(self.log_view.textCursor().MoveOperation.End)
        self.log_view.insertPlainText(text)
        # 자동 스크롤
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
