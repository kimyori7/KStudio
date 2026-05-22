"""편집 제안 미리보기 카드 — chat_panel.py 에서 분리 (Task 7).

동작 변경 없음.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .styles import _BUBBLE_STYLES, _ACTION_LABEL_KO, _TYPE_LABEL_KO


def _format_proposal_line(p: dict) -> str:
    """카드의 proposals 리스트 한 줄 — 사람 읽을 수 있는 요약."""
    action = _ACTION_LABEL_KO.get(p.get("action", ""), p.get("action", "?"))
    eff_type = _TYPE_LABEL_KO.get(p.get("type", ""), p.get("type", ""))
    payload = p.get("payload", {}) or {}
    if p.get("action") == "remove":
        eid = payload.get("effect_id", "?")
        return f"• {action}: 효과 {eid}"
    if p.get("action") == "modify":
        eid = payload.get("effect_id", "?")
        keys = [k for k in payload.keys() if k != "effect_id"]
        return f"• {action}: 효과 {eid} ({', '.join(keys)})"
    # add
    in_ms = payload.get("in_ms", 0)
    out_ms = payload.get("out_ms", 0)
    detail = f"{in_ms}ms~{out_ms}ms"
    if payload.get("text"):
        text = str(payload["text"])
        if len(text) > 30:
            text = text[:27] + "…"
            detail += f" \"{text}\""
        else:
            detail += f" \"{text}\""
    elif payload.get("rate"):
        detail += f" rate={payload['rate']}"
    elif payload.get("src"):
        src = str(payload["src"]).split("/")[-1].split("\\")[-1]
        detail += f" src={src}"
    return f"• {action} {eff_type}: {detail}"


class ProposalsPreviewCard(QFrame):
    """propose_* 큐의 변경 사항을 미리 보여주고 적용/취소 받는 카드 (interactive bubble).

    Apply / Cancel 버튼 클릭 시 시그널 emit. 한 번 클릭되면 버튼 비활성화 (재클릭 방지).
    """

    apply_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(
        self,
        proposals: list[dict],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(_BUBBLE_STYLES["proposals_preview"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)

        title = QLabel(f"📝 Claude 의 편집 제안 {len(proposals)}개 — 적용할까요?")
        title.setStyleSheet("color:#7dd3fc;font-weight:bold;")
        title.setWordWrap(True)
        lay.addWidget(title)

        list_text = "\n".join(_format_proposal_line(p) for p in proposals)
        body = QLabel(list_text)
        body.setStyleSheet("color:#dbeafe;font-family:Consolas,monospace;font-size:11px;")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._apply_btn = QPushButton("✓ 적용")
        self._apply_btn.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border:none;border-radius:4px;padding:6px 12px;font-weight:bold;}"
            "QPushButton:hover{background:#15803d;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        self._cancel_btn = QPushButton("✗ 취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:white;border:none;border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#991b1b;}"
            "QPushButton:disabled{background:#374151;color:#9ca3af;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._decided = False

    def _on_apply(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock()
        self.apply_clicked.emit()

    def _on_cancel(self) -> None:
        if self._decided:
            return
        self._decided = True
        self._lock()
        self.cancel_clicked.emit()

    def _lock(self) -> None:
        self._apply_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

    def mark_resolved(self, outcome: str) -> None:
        """외부에서 (다른 경로로 적용/취소된 경우) 카드 상태 표시."""
        self._decided = True
        self._lock()
        if outcome == "applied":
            self._apply_btn.setText("✓ 적용됨")
        elif outcome == "canceled":
            self._cancel_btn.setText("✗ 취소됨")
