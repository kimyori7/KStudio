"""문서 비교(DIFF) 뷰 — 순수 diff 코어 + 좌/우 편집 패널.

- compute_diff(left, right): Qt 의존 없는 순수 함수(테스트 코어). 줄 단위 diff + 변경 줄의
  글자 단위 diff 를 마크로 반환.
- DiffPane(MarkdownEditor): 한 칸. diff 색만 extraSelections 로 입힌다(거터/폰트/autoscroll 상속).
- DiffView(QWidget): 좌/우 패널 + 디바운스 재계산 + 채움/드롭 + 스크롤 동기.
  왼쪽은 setDocument 로 탭 문서를 공유(복사/되쓰기 없음), 오른쪽은 독립 문서+경로+dirty.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ..tokens import DIFF_COLORS
from .editor import MarkdownEditor
from .highlighter import MarkdownHighlighter


# ---------- 순수 diff 코어 ----------
@dataclass
class LineMark:
    line: int
    kind: str   # "added" | "deleted" | "changed"


@dataclass
class CharMark:
    line: int
    start: int
    end: int    # 배타


@dataclass
class SideMarks:
    lines: list[LineMark] = field(default_factory=list)
    chars: list[CharMark] = field(default_factory=list)


def _split(text: str) -> list[str]:
    return text.splitlines()


def compute_diff(left: str, right: str) -> tuple[SideMarks, SideMarks]:
    """두 텍스트의 차이를 좌/우 마크로. 줄 단위 + 변경 줄의 글자 단위."""
    la, ra = _split(left), _split(right)
    lm, rm = SideMarks(), SideMarks()
    sm = difflib.SequenceMatcher(a=la, b=ra, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for i in range(i1, i2):
                lm.lines.append(LineMark(i, "deleted"))
        elif tag == "insert":
            for j in range(j1, j2):
                rm.lines.append(LineMark(j, "added"))
        elif tag == "replace":
            for i in range(i1, i2):
                lm.lines.append(LineMark(i, "changed"))
            for j in range(j1, j2):
                rm.lines.append(LineMark(j, "changed"))
            # 변경 블록의 줄을 인덱스로 짝지어 글자 단위 정밀화.
            for k in range(min(i2 - i1, j2 - j1)):
                _char_diff(la[i1 + k], ra[j1 + k], i1 + k, j1 + k, lm, rm)
    return lm, rm


def _char_diff(a: str, b: str, aline: int, bline: int,
               lm: SideMarks, rm: SideMarks) -> None:
    cm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in cm.get_opcodes():
        if tag in ("delete", "replace") and i2 > i1:
            lm.chars.append(CharMark(aline, i1, i2))
        if tag in ("insert", "replace") and j2 > j1:
            rm.chars.append(CharMark(bline, j1, j2))


# ---------- 패널 ----------
class DiffPane(MarkdownEditor):
    """DIFF 한 칸. diff 색만 extraSelections 로 입힌다(다른 용도 사용 안 함 → 충돌 없음).

    빈 칸은 placeholder 를 보이고, 클릭하면 clicked_empty 로 채움(파일 선택)을 요청한다.
    파일 URL 드롭을 받으면 file_dropped 로 그 칸에 로드를 요청한다.
    """
    clicked_empty = Signal()
    file_dropped = Signal(object)   # Path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("클릭하거나 .md 파일을 끌어다 놓으세요")
        self.setAcceptDrops(True)
        # 드래그-오버 안내 오버레이.
        self._drop_hint = QLabel("여기에 배치 ↓", self)
        self._drop_hint.setStyleSheet(
            "background: rgba(245, 158, 11, 235); color: #1A1D24;"
            " padding: 8px 18px; border-radius: 10px; font-weight: bold;"
        )
        self._drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._drop_hint.hide()

    def apply_marks(self, marks: SideMarks) -> None:
        """줄 마크(full-width 배경) + 글자 마크(범위 배경)를 extraSelections 로 적용."""
        doc = self.document()
        sels: list[QTextEdit.ExtraSelection] = []
        for lm in marks.lines:
            blk = doc.findBlockByNumber(lm.line)
            if not blk.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(blk)
            sel.format.setBackground(QColor(DIFF_COLORS[f"{lm.kind}_line"]))
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sels.append(sel)
        for cm in marks.chars:
            blk = doc.findBlockByNumber(cm.line)
            if not blk.isValid():
                continue
            cur = QTextCursor(blk)
            cur.setPosition(blk.position() + cm.start)
            cur.setPosition(blk.position() + cm.end, QTextCursor.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format.setBackground(QColor(DIFF_COLORS["char"]))
            sels.append(sel)
        self.setExtraSelections(sels)

    # --- 빈 칸 클릭 → 파일 선택 요청 ---
    def mousePressEvent(self, e) -> None:  # type: ignore[override]
        if e.button() == Qt.LeftButton and not self.toPlainText():
            self.clicked_empty.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    # --- 파일 드롭 ---
    @staticmethod
    def _accepted_path(mime) -> Path | None:
        if not mime.hasUrls():
            return None
        for u in mime.urls():
            if not u.isLocalFile():
                continue
            p = Path(u.toLocalFile())
            if p.is_file() and p.suffix.lower() in (".md", ".markdown"):
                return p
        return None

    def _show_hint(self) -> None:
        self._drop_hint.adjustSize()
        self._drop_hint.move(
            max(8, (self.width() - self._drop_hint.width()) // 2),
            max(8, (self.height() - self._drop_hint.height()) // 2),
        )
        self._drop_hint.raise_()
        self._drop_hint.show()

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._accepted_path(event.mimeData()) is not None:
            event.acceptProposedAction()
            self._show_hint()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._accepted_path(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drop_hint.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._drop_hint.hide()
        p = self._accepted_path(event.mimeData())
        if p is None:
            event.ignore()
            return
        self.file_dropped.emit(p)
        event.acceptProposedAction()


# ---------- 뷰 ----------
class DiffView(QWidget):
    """좌/우 DiffPane + 실시간 재계산 + 채움/드롭 + 스크롤 동기."""
    right_dirty_changed = Signal()
    pane_filled = Signal(str, object)   # side("left"/"right"), Path
    request_fill = Signal(str)          # side — 빈 칸 클릭 → 파일 선택 요청

    _DEBOUNCE_MS = 200

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.left = DiffPane()
        self.right = DiffPane()
        # 오른쪽은 독립 문서 — 문법 강조용 하이라이터 부착(왼쪽은 공유 문서에 이미 있음).
        self._right_hl = MarkdownHighlighter(self.right.document())

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.left)
        self._splitter.addWidget(self.right)
        self._splitter.setSizes([500, 500])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._splitter)

        self.right_path: Path | None = None
        self.right_dirty = False
        self._left_filled = False    # blank 탭에서 파일로 채워졌는지

        # 실시간 재계산 — 어느 쪽이든 변경되면 디바운스 후 색 다시 계산.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._recompute)
        self.left.textChanged.connect(self._debounce.start)
        self.right.textChanged.connect(self._on_right_text_changed)

        # 스크롤 동기 (비율).
        self._sync = False
        self.left.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.left, self.right))
        self.right.verticalScrollBar().valueChanged.connect(
            lambda _v: self._sync_scroll(self.right, self.left))

        # 빈 칸 클릭 → 채움 요청.
        self.left.clicked_empty.connect(lambda: self.request_fill.emit("left"))
        self.right.clicked_empty.connect(lambda: self.request_fill.emit("right"))
        # 드롭 → 해당 칸 로드.
        self.left.file_dropped.connect(lambda p: self.load_side("left", p))
        self.right.file_dropped.connect(lambda p: self.load_side("right", p))

    # --- 왼쪽: 탭 문서 공유 ---
    def set_left_document(self, doc) -> None:
        """왼쪽 패널이 탭 문서(QTextDocument)를 공유 — 편집이 양방향 자동 반영."""
        self.left.setDocument(doc)
        # 공유 직후 한 번 색 계산.
        self._recompute()

    # --- 채움 ---
    def _left_is_empty(self) -> bool:
        return not self._left_filled and not self.left.toPlainText().strip()

    def _right_is_empty(self) -> bool:
        return self.right_path is None and not self.right.toPlainText().strip()

    def has_empty_pane(self) -> bool:
        return self._left_is_empty() or self._right_is_empty()

    def fill_next(self, path: Path) -> None:
        """첫 빈 칸(왼→오)을 채운다."""
        self.load_side("left" if self._left_is_empty() else "right", Path(path))

    def load_side(self, side: str, path: Path) -> None:
        from ..markdown_tab import _read_text_with_fallback
        path = Path(path)
        text = _read_text_with_fallback(path)
        if side == "left":
            self.left.setPlainText(text)
            self._left_filled = True
            self.pane_filled.emit("left", path)
        else:
            self.right.setPlainText(text)
            self.right_path = path
            self.right_dirty = False
            self.pane_filled.emit("right", path)
            self.right_dirty_changed.emit()
        self._recompute()

    # --- 오른쪽 dirty/저장 ---
    def _on_right_text_changed(self) -> None:
        if not self.right_dirty:
            self.right_dirty = True
            self.right_dirty_changed.emit()
        self._debounce.start()

    def right_text(self) -> str:
        return self.right.toPlainText()

    def right_has_focus(self) -> bool:
        return self.right.hasFocus()

    def mark_right_saved(self, path: Path) -> None:
        self.right_path = Path(path)
        self.right_dirty = False
        self.right_dirty_changed.emit()

    # --- 재계산 / 스크롤 ---
    def _recompute(self) -> None:
        lm, rm = compute_diff(self.left.toPlainText(), self.right.toPlainText())
        self.left.apply_marks(lm)
        self.right.apply_marks(rm)

    def _sync_scroll(self, src: DiffPane, dst: DiffPane) -> None:
        if self._sync:
            return
        self._sync = True
        try:
            s = src.verticalScrollBar()
            d = dst.verticalScrollBar()
            ratio = s.value() / s.maximum() if s.maximum() > 0 else 0.0
            d.setValue(int(d.maximum() * ratio))
        finally:
            self._sync = False
