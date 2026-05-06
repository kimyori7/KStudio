"""환경설정 → MCP 패널.

KStudio 의 LLM 통합 토글 + CLI 자동 등록 + 외부 터미널 launcher. UX:
- 활성 체크박스 → 즉시 효과 X (KStudio 재시작 필요), 안내 라벨 표시.
- 토큰: read-only, 복사 버튼 + 재생성 버튼.
- 포트: 0 = 자동, 또는 특정 번호 강제.
- "CLI 등록" 버튼 → claude/gemini/codex 일괄 시도, 결과 alert.
- "터미널에서 실행" 버튼들 → 외부 Windows Terminal 또는 cmd.exe 에서 CLI 시작.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import McpSettings


class McpPanel(QWidget):
    """LLM CLI 통합 (MCP) 설정 패널."""

    def __init__(self, mcp: McpSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mcp = mcp

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        # 헤더
        header = QLabel(
            "<b>LLM CLI 통합 (MCP)</b><br/>"
            "Claude Code · Gemini CLI · OpenAI Codex 가 KStudio 를 자연어로 제어할 수 있게 합니다.<br/>"
            "<span style='color:#A0A4AB;'>HTTP 브리지는 127.0.0.1 만 bind 하며 외부에 노출되지 않습니다.</span>"
        )
        header.setWordWrap(True)
        root.addWidget(header)

        # 활성 체크
        self.enable_chk = QCheckBox("MCP 통합 활성화 (다음 KStudio 재시작부터 적용)")
        self.enable_chk.setChecked(mcp.enabled)
        self.enable_chk.toggled.connect(self._on_enable_toggled)
        root.addWidget(self.enable_chk)

        # 파괴적 작업 토글
        self.destructive_chk = QCheckBox(
            "파괴적 작업 허용 (원본 파일 덮어쓰기/삭제). 비추천 — 기본 OFF."
        )
        self.destructive_chk.setChecked(mcp.allow_destructive)
        self.destructive_chk.toggled.connect(
            lambda v: setattr(self._mcp, "allow_destructive", v)
        )
        root.addWidget(self.destructive_chk)

        # 연결 정보
        info = QFrame()
        info.setFrameShape(QFrame.StyledPanel)
        form = QFormLayout(info)

        # 토큰 표시 + 복사
        token_row = QHBoxLayout()
        self.token_edit = QLineEdit(mcp.token or "(첫 활성화 시 자동 생성)")
        self.token_edit.setReadOnly(True)
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_show_chk = QCheckBox("표시")
        self.token_show_chk.toggled.connect(
            lambda v: self.token_edit.setEchoMode(
                QLineEdit.Normal if v else QLineEdit.Password
            )
        )
        copy_btn = QPushButton("복사")
        copy_btn.clicked.connect(self._copy_token)
        regen_btn = QPushButton("재생성")
        regen_btn.setToolTip(
            "새 토큰을 발급. 기존에 등록된 CLI 는 다시 등록해야 합니다."
        )
        regen_btn.clicked.connect(self._regen_token)
        token_row.addWidget(self.token_edit, stretch=1)
        token_row.addWidget(self.token_show_chk)
        token_row.addWidget(copy_btn)
        token_row.addWidget(regen_btn)
        form.addRow("토큰:", token_row)

        # 포트 입력
        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setValue(mcp.port)
        self.port_spin.setSpecialValueText("0 = 자동")
        self.port_spin.valueChanged.connect(
            lambda v: setattr(self._mcp, "port", v)
        )
        form.addRow("포트:", self.port_spin)

        root.addWidget(info)

        # CLI 등록 + 실행
        cli_box = QFrame()
        cli_box.setFrameShape(QFrame.StyledPanel)
        cli_root = QVBoxLayout(cli_box)
        cli_root.addWidget(QLabel("<b>1. CLI 에 KStudio 등록</b>"))
        cli_root.addWidget(QLabel(
            "각 CLI 의 설정 파일에 KStudio 를 MCP 서버로 등록합니다. "
            "이미 등록된 KStudio 는 새 설정으로 갱신됩니다."
        ))
        register_btn = QPushButton("Claude / Gemini / Codex 에 일괄 등록")
        register_btn.clicked.connect(self._register_all_clis)
        cli_root.addWidget(register_btn)

        cli_root.addSpacing(10)
        cli_root.addWidget(QLabel("<b>2. 터미널에서 CLI 실행</b>"))
        cli_root.addWidget(QLabel(
            "Windows Terminal 또는 cmd.exe 새 창에서 LLM CLI 를 시작합니다. "
            "그 안에서 자연어로 KStudio 를 시키면 됩니다."
        ))
        btns = QHBoxLayout()
        for label, cmd in [
            ("Claude Code", "claude"),
            ("Gemini CLI", "gemini"),
            ("Codex", "codex"),
            ("PowerShell", "pwsh"),
        ]:
            b = QPushButton(label)
            b.clicked.connect(lambda _, c=cmd: self._launch_terminal(c))
            btns.addWidget(b)
        cli_root.addLayout(btns)
        root.addWidget(cli_box)

        root.addStretch(1)

    # ---------- 핸들러 ----------

    def _on_enable_toggled(self, v: bool) -> None:
        self._mcp.enabled = v

    def _copy_token(self) -> None:
        if not self._mcp.token:
            QMessageBox.information(
                self, "토큰", "토큰이 아직 생성되지 않았습니다. "
                "MCP 활성화 후 KStudio 를 한 번 실행하면 자동 생성됩니다."
            )
            return
        QApplication.clipboard().setText(self._mcp.token, QClipboard.Clipboard)
        QMessageBox.information(self, "토큰", "토큰을 클립보드에 복사했습니다.")

    def _regen_token(self) -> None:
        from ...mcp.bridge_server import generate_token
        ret = QMessageBox.question(
            self, "토큰 재생성",
            "기존 토큰이 폐기되고 새 토큰이 발급됩니다.\n"
            "이미 등록된 CLI 는 'CLI 등록' 으로 다시 등록해야 합니다.\n계속할까요?",
        )
        if ret != QMessageBox.Yes:
            return
        self._mcp.token = generate_token()
        self.token_edit.setText(self._mcp.token)

    def _register_all_clis(self) -> None:
        if not self._mcp.token or not self._mcp.port:
            QMessageBox.warning(
                self, "등록 불가",
                "먼저 MCP 를 활성화하고 KStudio 를 한 번 실행해 토큰/포트가 "
                "할당되도록 하세요.",
            )
            return
        from ...mcp.cli_register import register_all
        results = register_all(self._mcp.port, self._mcp.token)
        msgs = []
        for cli, (ok, msg) in results.items():
            mark = "✓" if ok else "✗"
            msgs.append(f"{mark} {cli}: {msg}")
        QMessageBox.information(self, "CLI 등록 결과", "\n\n".join(msgs))

    def _launch_terminal(self, command: str) -> None:
        """외부 터미널에서 명령 실행 — Windows Terminal 우선, 없으면 cmd.exe."""
        # claude/gemini/codex 가 실제 PATH 에 있는지 검사 — 없으면 안내 후 그래도 시도.
        if command not in ("pwsh", "cmd"):
            if shutil.which(command) is None:
                ret = QMessageBox.question(
                    self, "CLI 미발견",
                    f"'{command}' 가 PATH 에 없습니다. 그래도 터미널을 열까요?",
                )
                if ret != QMessageBox.Yes:
                    return
        try:
            wt = shutil.which("wt.exe")
            if wt:
                # Windows Terminal — 새 탭에서 실행, 시작 폴더는 사용자 홈.
                subprocess.Popen(
                    [wt, "-w", "0", "nt", "-d", str(Path.home()), command],
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
            else:
                # fallback: cmd.exe — 새 창에서 명령 실행 후 prompt 유지(/k).
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "cmd.exe", "/k", command],
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
        except OSError as e:
            QMessageBox.warning(self, "터미널 실행 실패", str(e))
