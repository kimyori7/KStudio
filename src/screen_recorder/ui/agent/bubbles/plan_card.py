"""편집 plan 카드 — chat_panel.py 에서 분리 (Task 7).

동작 변경 없음.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from .styles import _BUBBLE_STYLES


class PlanCard(QFrame):
    """편집 plan 카드 — submit_plan 도구가 emit 한 (plan_id, summary, markdown) 표시.

    상태: pending → (approved | rejected).
    ✓ → approved 시그널 + 헤더에 (진행 중) 표시.
    ✗ → textarea + [전송]/[그냥 닫기] 등장. 둘 다 rejected(reason) emit (전송=입력 내용, 그냥 닫기="").
    mark_externally_resolved — PlanGate.cancel_all 처럼 외부에서 결정된 경우.
    """

    approved = Signal()
    rejected = Signal(str)   # reason — "" 면 사유 없이 거부.

    def __init__(
        self,
        plan_id: str,
        summary: str,
        markdown: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._plan_id = plan_id
        self._summary = summary
        self.setStyleSheet(_BUBBLE_STYLES["plan_card"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        # 헤더 — 📋 아이콘 + summary + ✓/✗ 버튼 같은 줄.
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self._title = QLabel(f"📋 {summary}")
        self._title.setStyleSheet("color:#7dd3fc;font-weight:bold;")
        self._title.setWordWrap(True)
        header_row.addWidget(self._title, 1)

        self._approve_btn = QPushButton("✓ 진행")
        self._approve_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border:none;"
            "border-radius:4px;padding:6px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._approve_btn.clicked.connect(self._on_approve)
        self._reject_btn = QPushButton("✗ 취소")
        self._reject_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;"
            "border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._reject_btn.clicked.connect(self._on_reject)
        header_row.addWidget(self._approve_btn)
        header_row.addWidget(self._reject_btn)
        lay.addLayout(header_row)

        # 본문 — markdown.
        self._body = QLabel(markdown)
        self._body.setStyleSheet("color:#e0f2fe;")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.MarkdownText)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        lay.addWidget(self._body)

        # 거부 사유 입력 영역 — 초기엔 숨김.
        self._reason_label = QLabel("거부 사유 (선택):")
        self._reason_label.setStyleSheet("color:#fca5a5;font-size:11px;")
        self._reason_label.setVisible(False)
        lay.addWidget(self._reason_label)

        self._reason_input = QPlainTextEdit()
        self._reason_input.setStyleSheet(
            "QPlainTextEdit{background:#0f172a;color:#e0f2fe;border:1px solid #334155;"
            "border-radius:4px;padding:4px 6px;font-size:12px;}"
        )
        self._reason_input.setFixedHeight(60)
        self._reason_input.setVisible(False)
        lay.addWidget(self._reason_input)

        reason_btn_row = QHBoxLayout()
        reason_btn_row.setSpacing(6)
        self._send_reason_btn = QPushButton("전송")
        self._send_reason_btn.setStyleSheet(
            "QPushButton{background:#1e293b;color:#e0f2fe;border:1px solid #475569;"
            "border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#334155;}"
        )
        self._send_reason_btn.clicked.connect(self._on_send_reason)
        self._send_reason_btn.setVisible(False)
        self._close_no_reason_btn = QPushButton("그냥 닫기")
        self._close_no_reason_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#94a3b8;border:1px solid #475569;"
            "border-radius:4px;padding:4px 10px;}"
            "QPushButton:hover{background:#1e293b;}"
        )
        self._close_no_reason_btn.clicked.connect(self._on_close_no_reason)
        self._close_no_reason_btn.setVisible(False)
        reason_btn_row.addWidget(self._send_reason_btn)
        reason_btn_row.addWidget(self._close_no_reason_btn)
        reason_btn_row.addStretch(1)
        lay.addLayout(reason_btn_row)

        self._decided = False

    def plan_id(self) -> str:
        return self._plan_id

    def _on_approve(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock_main_buttons()
        # 헤더에 "(진행 중)" 추가 (중복 방지).
        suffix = " (진행 중)"
        if suffix not in self._title.text():
            self._title.setText(self._title.text() + suffix)
        self.approved.emit()

    def _on_reject(self) -> None:
        if self._decided:
            return
        # decided 는 아직 — textarea 보여주고 [전송]/[그냥 닫기] 기다림.
        self._lock_main_buttons()
        self._reason_label.setVisible(True)
        self._reason_input.setVisible(True)
        self._send_reason_btn.setVisible(True)
        self._close_no_reason_btn.setVisible(True)
        self._reason_input.setFocus()

    def _on_send_reason(self) -> None:
        if self._decided:
            return
        self._decided = True
        reason = self._reason_input.toPlainText().strip()
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        self._reason_input.setReadOnly(True)
        self.rejected.emit(reason)

    def _on_close_no_reason(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        self._reason_input.setReadOnly(True)
        self.rejected.emit("")

    def _lock_main_buttons(self) -> None:
        self._approve_btn.setEnabled(False)
        self._reject_btn.setEnabled(False)

    def mark_externally_resolved(self, outcome: str) -> None:
        """외부에서 (예: cancel_all) 결정된 경우 — 버튼 비활성 + 헤더 갱신.

        outcome: 'approved' / 'rejected' / 'cancelled'.
        """
        self._decided = True
        self._lock_main_buttons()
        self._send_reason_btn.setEnabled(False)
        self._close_no_reason_btn.setEnabled(False)
        suffix = {"approved": " (진행 중)", "rejected": " (거부됨)", "cancelled": " (취소됨)"}.get(outcome, "")
        if suffix and suffix not in self._title.text():
            self._title.setText(self._title.text() + suffix)
