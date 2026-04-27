"""왼쪽 수직 도구 팔레트 — 선택 / 사각형 / 화살표 / 텍스트."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton, QButtonGroup


_TOOLS = [
    ("select", "▸", "선택 (V)", "V"),
    ("rect",   "□", "사각형 (R)", "R"),
    ("arrow",  "→", "화살표 (A)", "A"),
    ("text",   "T", "텍스트 (T)", "T"),
]


class ToolPalette(QWidget):
    tool_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ToolPalette")
        self.setFixedWidth(38)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(2)

        self._buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for tid, icon, tip, shortcut in _TOOLS:
            btn = QToolButton()
            btn.setText(icon)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setFixedSize(32, 28)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _chk=False, t=tid: self._on_clicked(t))
            self._buttons[tid] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)
            QShortcut(QKeySequence(shortcut), self, activated=lambda t=tid: self._on_clicked(t))

        layout.addStretch(1)
        self._current = "select"
        self._buttons["select"].setChecked(True)

    def current_tool(self) -> str:
        return self._current

    def set_current_tool(self, tid: str) -> None:
        self._on_clicked(tid)

    def _on_clicked(self, tid: str) -> None:
        if tid not in self._buttons:
            return
        if tid == self._current:
            return
        self._current = tid
        self._buttons[tid].setChecked(True)
        self.tool_changed.emit(tid)
