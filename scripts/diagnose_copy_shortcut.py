"""ShortcutOverride 판별 — 어떤 위젯이 Ctrl+C 를 스스로 가로채는가(=WindowShortcut 이김).

True  = 위젯이 ShortcutOverride 를 accept → 포커스 시 Ctrl+C 가 위젯으로 (WindowShortcut 못 가져감)
False = accept 안 함 → WindowShortcut(Ctrl+C) 가 키를 가로채 위젯이 못 받음
"""
import os
os.environ.setdefault("KSTUDIO_SETTINGS_DIR", os.path.join(os.environ["TEMP"], "kstudio_dev"))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTextBrowser

from screen_recorder.ui.markdown.editor import MarkdownEditor


def overrides_copy(w) -> bool:
    ev = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_C, Qt.ControlModifier)
    QApplication.sendEvent(w, ev)
    return ev.isAccepted()


app = QApplication([])

# 1) 표준 QPlainTextEdit(편집 가능) — 방법론 sanity. True 여야 함.
plain = QPlainTextEdit()
plain.setPlainText("hello world")
print("plain QPlainTextEdit (editable):      ", overrides_copy(plain))

# 2) 마크다운 에디터(편집 가능) — 사용자 보고 위젯.
ed = MarkdownEditor()
ed.setPlainText("# title\n\nsome **text** here")
print("MarkdownEditor (editable, no sel):    ", overrides_copy(ed))
cur = ed.textCursor(); cur.select(cur.SelectionType.Document); ed.setTextCursor(cur)
print("MarkdownEditor (editable, with sel):  ", overrides_copy(ed))

# 3) 읽기 전용 QTextBrowser — Fallback 미리보기. False 일 것(WindowShortcut 가 가로챔).
br = QTextBrowser()
br.setHtml("<p>some <b>text</b> here</p>")
print("QTextBrowser (read-only, no sel):     ", overrides_copy(br))
br.selectAll()
print("QTextBrowser (read-only, with sel):   ", overrides_copy(br))
