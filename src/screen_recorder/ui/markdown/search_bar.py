"""Markdown 찾기/바꾸기 바 — 에디터(QPlainTextEdit) 기준 검색.

사용자 결정(2026-05-29): 검색은 **에디터 raw 텍스트** 기준. 미리보기는 자체 하이라이트
없이 **위치만 따라간다**(on_navigate 콜백 → 탭이 미리보기 스크롤 동기화). 미리보기가 렌더
결과물(HTML)이라 `**굵게**` 의 `*` 기호 등 글자가 달라 개별 하이라이트는 혼란 → 단순화.

- 모든 매치: 연한 amber 배경(extraSelections), 현재 매치: 에디터 실제 selection 으로 구분.
- Ctrl+F=찾기 / Ctrl+H=찾기+바꾸기. Enter=다음, Shift+Enter=이전, Esc=닫기.
- 대소문자 토글(Aa). 바꾸기는 에디터 텍스트에 적용 → content_changed 로 미리보기 자동 갱신.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import (
    QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTextEdit, QWidget,
)

# 매치 배경색 — 문서 모드 amber 테마와 어울리는 어두운 금색(다크 본문 위 가독성 유지).
_MATCH_BG = QColor("#4a3c12")


class MarkdownSearchBar(QWidget):
    def __init__(
        self,
        editor: QPlainTextEdit,
        *,
        on_navigate: Optional[Callable[[], None]] = None,
        on_query_changed: Optional[Callable[[str, bool], None]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._on_navigate = on_navigate
        # 검색어/대소문자 변경 시 (query, case) 알림 — 미리보기 하이라이트 동기화용.
        self._on_query_changed = on_query_changed
        self._matches: list[QTextCursor] = []
        self._current = -1
        self._case = False
        self._busy = False   # 바꾸기 도중 doc textChanged 재진입 차단

        # --- UI ---
        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("찾기")
        self._find_edit.setClearButtonEnabled(True)
        self._count = QLabel("")
        self._count.setMinimumWidth(60)
        self._btn_prev = QPushButton("▲")
        self._btn_next = QPushButton("▼")
        self._btn_case = QPushButton("Aa")
        self._btn_case.setCheckable(True)
        self._btn_case.setToolTip("대소문자 구분")
        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("바꾸기")
        self._btn_replace = QPushButton("바꾸기")
        self._btn_replace_all = QPushButton("모두")
        self._btn_close = QPushButton("✕")
        for b in (self._btn_prev, self._btn_next, self._btn_case,
                  self._btn_replace, self._btn_replace_all, self._btn_close):
            b.setFocusPolicy(Qt.NoFocus)   # 입력칸 포커스 유지(연속 타이핑/Enter)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(4)
        row.addWidget(self._find_edit, stretch=2)
        row.addWidget(self._count)
        row.addWidget(self._btn_prev)
        row.addWidget(self._btn_next)
        row.addWidget(self._btn_case)
        row.addWidget(self._replace_edit, stretch=2)
        row.addWidget(self._btn_replace)
        row.addWidget(self._btn_replace_all)
        row.addWidget(self._btn_close)

        # --- 시그널 ---
        self._find_edit.textChanged.connect(lambda _t: self._recompute(move_cursor=True))
        self._find_edit.returnPressed.connect(self.find_next)
        self._replace_edit.returnPressed.connect(self.replace_current)
        self._btn_prev.clicked.connect(self.find_prev)
        self._btn_next.clicked.connect(self.find_next)
        self._btn_case.toggled.connect(self._on_case_toggled)
        self._btn_replace.clicked.connect(self.replace_current)
        self._btn_replace_all.clicked.connect(self.replace_all)
        self._btn_close.clicked.connect(self.close_bar)
        # 문서가 (다른 곳에서) 편집되면 하이라이트만 갱신(커서 이동 X — 타이핑 방해 금지).
        self._editor.textChanged.connect(self._on_doc_changed)
        # Shift+Enter=이전 / Esc=닫기.
        self._find_edit.installEventFilter(self)
        self._replace_edit.installEventFilter(self)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close_bar)

    # ---------- 열기/닫기 ----------
    def open_find(self) -> None:
        self._set_replace_visible(False)
        self._prefill_from_selection()
        self.show()
        self._find_edit.setFocus()
        self._find_edit.selectAll()
        self._recompute(move_cursor=True)

    def open_replace(self) -> None:
        self._set_replace_visible(True)
        self._prefill_from_selection()
        self.show()
        self._find_edit.setFocus()
        self._find_edit.selectAll()
        self._recompute(move_cursor=True)

    def close_bar(self) -> None:
        self._editor.setExtraSelections([])
        self._matches = []
        self._current = -1
        if self._on_query_changed is not None:
            self._on_query_changed("", self._case)   # 미리보기 하이라이트 해제
        self.hide()
        self._editor.setFocus()

    def _set_replace_visible(self, visible: bool) -> None:
        self._replace_edit.setVisible(visible)
        self._btn_replace.setVisible(visible)
        self._btn_replace_all.setVisible(visible)

    def _prefill_from_selection(self) -> None:
        sel = self._editor.textCursor().selectedText()
        # QTextCursor.selectedText 는 줄바꿈을 U+2029 로 주므로 한 줄 선택만 prefill.
        if sel and " " not in sel:
            self._find_edit.setText(sel)

    # ---------- 검색 상태 (공개 API / 테스트) ----------
    def set_query(self, text: str) -> None:
        self._find_edit.setText(text)   # textChanged → _recompute

    def set_replacement(self, text: str) -> None:
        self._replace_edit.setText(text)

    def set_case_sensitive(self, on: bool) -> None:
        self._btn_case.setChecked(on)   # toggled → _on_case_toggled → recompute

    def match_count(self) -> int:
        return len(self._matches)

    def current_index(self) -> int:
        return self._current

    def _on_case_toggled(self, on: bool) -> None:
        self._case = on
        self._recompute(move_cursor=True)

    # ---------- 핵심 ----------
    def _find_flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self._case:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def _recompute(self, *, move_cursor: bool) -> None:
        needle = self._find_edit.text()
        prev_pos = None
        if 0 <= self._current < len(self._matches):
            prev_pos = self._matches[self._current].selectionStart()

        self._matches = []
        if needle:
            doc = self._editor.document()
            flags = self._find_flags()
            cur = QTextCursor(doc)
            while True:
                cur = doc.find(needle, cur, flags)
                if cur.isNull():
                    break
                self._matches.append(QTextCursor(cur))

        if not self._matches:
            self._current = -1
        elif prev_pos is not None:
            self._current = 0
            for i, c in enumerate(self._matches):
                if c.selectionStart() >= prev_pos:
                    self._current = i
                    break
        else:
            self._current = 0

        self._apply_highlights()
        self._notify_query()
        self._update_count()
        if move_cursor:
            self._scroll_to_current()

    def _notify_query(self) -> None:
        """현재 검색어/대소문자를 외부(미리보기)에 알려 같은 단어를 강조하게 한다."""
        if self._on_query_changed is not None:
            self._on_query_changed(self._find_edit.text(), self._case)

    def _apply_highlights(self) -> None:
        sels: list[QTextEdit.ExtraSelection] = []
        for c in self._matches:
            sel = QTextEdit.ExtraSelection()
            sel.cursor = c
            fmt = QTextCharFormat()
            fmt.setBackground(_MATCH_BG)
            sel.format = fmt
            sels.append(sel)
        self._editor.setExtraSelections(sels)

    def _update_count(self) -> None:
        if not self._find_edit.text():
            self._count.setText("")
        elif not self._matches:
            self._count.setText("결과 없음")
        else:
            self._count.setText(f"{self._current + 1} / {len(self._matches)}")

    def _scroll_to_current(self) -> None:
        if not (0 <= self._current < len(self._matches)):
            return
        # 에디터 실제 selection 을 현재 매치로 → 시스템 selection 으로 현재 위치 강조 + 스크롤.
        # (find 입력칸 포커스는 유지됨 — setTextCursor 는 포커스를 옮기지 않음.)
        self._editor.setTextCursor(QTextCursor(self._matches[self._current]))
        self._editor.ensureCursorVisible()
        if self._on_navigate is not None:
            self._on_navigate()

    def find_next(self) -> None:
        if not self._matches:
            return
        self._current = (self._current + 1) % len(self._matches)
        self._update_count()
        self._scroll_to_current()

    def find_prev(self) -> None:
        if not self._matches:
            return
        self._current = (self._current - 1) % len(self._matches)
        self._update_count()
        self._scroll_to_current()

    # ---------- 바꾸기 ----------
    def replace_current(self) -> None:
        if not (0 <= self._current < len(self._matches)):
            return
        self._busy = True
        try:
            QTextCursor(self._matches[self._current]).insertText(self._replace_edit.text())
        finally:
            self._busy = False
        self._recompute(move_cursor=True)

    def replace_all(self) -> int:
        if not self._matches:
            return 0
        rep = self._replace_edit.text()
        n = len(self._matches)
        anchor = QTextCursor(self._editor.document())
        self._busy = True
        anchor.beginEditBlock()          # 한 번의 undo 로 묶기
        try:
            # 끝→시작 순서: 뒤쪽을 먼저 바꿔야 앞쪽 매치 위치가 안 흔들린다.
            for c in reversed(self._matches):
                QTextCursor(c).insertText(rep)
        finally:
            anchor.endEditBlock()
            self._busy = False
        self._recompute(move_cursor=True)
        return n

    # ---------- 이벤트 ----------
    def _on_doc_changed(self) -> None:
        if self._busy or not self.isVisible():
            return
        self._recompute(move_cursor=False)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.close_bar()
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter) and obj is self._find_edit:
                if event.modifiers() & Qt.ShiftModifier:
                    self.find_prev()
                    return True
        return super().eventFilter(obj, event)
