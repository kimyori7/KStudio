"""왼쪽 수직 도구 팔레트.

세 그룹:
1. 주석 도구 — Select / Rect / Arrow / Text (mutually exclusive)
2. 마스크 도구 — Magic Wand / Mask Brush (mutually exclusive with group 1)
3. 액션 — 자동 누끼 (one-shot, 도구 아님)
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton, QButtonGroup, QFrame


# (id, icon, tooltip, shortcut or None)
_TOOLS = [
    ("select", "🖐", "선택 (V) — 주석 객체를 잡고 이동·크기조정", "V"),
    ("selection", "▭",
     "영역 선택 (M) — 사각 영역 드래그. 이후 Ctrl+C 로 영역만 복사, "
     "Ctrl+X 로 잘라내기. ESC 로 해제.", "M"),
    ("rect",   "□", "사각형 (R)", "R"),
    ("arrow",  "→", "화살표 (A)", "A"),
    ("text",   "T", "텍스트 (T)", "T"),
    ("crop",   "✂", "자르기 (Crop) — 사각 영역 선택 후 Enter", None),
]
_PAINT_TOOLS = [
    ("brush",   "🖌",
     "브러시 — 활성 ImageLayer 픽셀에 직접 색칠. 옵션바에서 두께/색 조절", None),
    ("eraser",  "🧽",
     "지우개 — 활성 ImageLayer 픽셀의 알파를 0 으로 (투명하게). 옵션바에서 두께 조절", None),
]
_MASK_TOOLS = [
    ("magic_wand", "🪄",
     "마술봉 — 클릭하면 비슷한 색 영역이 빨강으로 미리보기. Enter/Delete 로 확정, Esc 로 취소. "
     "상단 옵션바의 '정도' 슬라이더로 색 허용 범위 조절", None),
    ("mask_brush", "🩹",
     "마스크 브러시 — 누끼 결과 다듬기. 상단 옵션바에서 [지우기]는 칠한 곳을 투명하게, "
     "[되살리기]는 자동 누끼/마술봉이 잘못 지운 영역을 다시 보이게", None),
]
# 액션 (도구 아님) — 토글 안 됨, 누르면 즉시 트리거
_ACTIONS = [
    ("auto_bg", "✨", "자동 누끼 (rembg) — 한 번에 배경 제거", None),
]


class ToolPalette(QWidget):
    tool_changed = Signal(str)         # 도구 선택 (mutually exclusive)
    action_triggered = Signal(str)     # 액션 버튼 클릭 (one-shot)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ToolPalette")
        self.setFixedWidth(48)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)

        self._buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        # 그룹 1 — 주석 도구
        for tid, icon, tip, shortcut in _TOOLS:
            btn = self._make_tool_button(icon, tip)
            btn.clicked.connect(lambda _chk=False, t=tid: self._on_clicked(t))
            self._buttons[tid] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)
            if shortcut:
                QShortcut(QKeySequence(shortcut), self,
                          activated=lambda t=tid: self._on_clicked(t))

        layout.addWidget(self._make_separator())

        # 그룹 2 — 페인트 도구 (래스터 픽셀 직접 수정)
        for tid, icon, tip, shortcut in _PAINT_TOOLS:
            btn = self._make_tool_button(icon, tip)
            btn.clicked.connect(lambda _chk=False, t=tid: self._on_clicked(t))
            self._buttons[tid] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)
            if shortcut:
                QShortcut(QKeySequence(shortcut), self,
                          activated=lambda t=tid: self._on_clicked(t))

        layout.addWidget(self._make_separator())

        # 그룹 3 — 마스크 도구
        for tid, icon, tip, shortcut in _MASK_TOOLS:
            btn = self._make_tool_button(icon, tip)
            btn.clicked.connect(lambda _chk=False, t=tid: self._on_clicked(t))
            self._buttons[tid] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)
            if shortcut:
                QShortcut(QKeySequence(shortcut), self,
                          activated=lambda t=tid: self._on_clicked(t))

        layout.addWidget(self._make_separator())

        # 그룹 3 — 액션 (one-shot)
        self._action_buttons: dict[str, QToolButton] = {}
        for aid, icon, tip, _shortcut in _ACTIONS:
            btn = QToolButton()
            btn.setText(icon)
            btn.setCheckable(False)
            btn.setFixedSize(40, 40)
            f = btn.font()
            f.setPointSize(18)
            btn.setFont(f)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _chk=False, a=aid: self.action_triggered.emit(a))
            self._action_buttons[aid] = btn
            layout.addWidget(btn)

        layout.addStretch(1)
        self._current = "select"
        self._buttons["select"].setChecked(True)

    # ---------- 외부 API ----------
    def current_tool(self) -> str:
        return self._current

    def set_current_tool(self, tid: str) -> None:
        self._on_clicked(tid)

    def find_action_button(self, aid: str) -> QToolButton | None:
        return self._action_buttons.get(aid)

    # ---------- 내부 ----------
    def _make_tool_button(self, icon: str, tip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(icon)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setFixedSize(40, 40)
        f = btn.font()
        f.setPointSize(18)
        btn.setFont(f)
        btn.setToolTip(tip)
        return btn

    def _make_separator(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("QFrame { color: #4A5060; margin: 2px 4px; }")
        f.setFixedHeight(1)
        return f

    def _on_clicked(self, tid: str) -> None:
        if tid not in self._buttons:
            return
        if tid == self._current:
            return
        self._current = tid
        self._buttons[tid].setChecked(True)
        self.tool_changed.emit(tid)
