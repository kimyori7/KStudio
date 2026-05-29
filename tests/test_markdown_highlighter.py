from PySide6.QtWidgets import QPlainTextEdit


def _formats_for_line(doc, line_idx):
    block = doc.findBlockByNumber(line_idx)
    return block.layout().formats() if block.layout() else []


def test_heading_is_highlighted(qtbot):
    from screen_recorder.ui.markdown.highlighter import MarkdownHighlighter
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    hl = MarkdownHighlighter(edit.document())
    edit.setPlainText("# Title\nplain text")
    assert _formats_for_line(edit.document(), 0), "heading 줄에 포맷이 있어야 함"
    assert not _formats_for_line(edit.document(), 1), "plain 줄엔 포맷 없음"


def test_fenced_code_block_state(qtbot):
    from screen_recorder.ui.markdown.highlighter import MarkdownHighlighter, IN_CODE
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    hl = MarkdownHighlighter(edit.document())
    edit.setPlainText("```python\ncode_line\n```\nafter")
    doc = edit.document()
    # fence 안 줄(1)은 코드 상태, fence 종료 후 줄(3)은 평문 상태
    assert doc.findBlockByNumber(1).userState() == IN_CODE
    assert doc.findBlockByNumber(3).userState() != IN_CODE
