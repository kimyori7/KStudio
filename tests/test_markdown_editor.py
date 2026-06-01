import pytest


def test_line_number_area_width_grows_with_lines(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("a")
    w1 = ed.line_number_area_width()
    ed.setPlainText("\n".join(str(i) for i in range(1000)))
    w2 = ed.line_number_area_width()
    assert w2 > w1  # 1000줄이면 자릿수가 늘어 거터 폭 증가


def test_content_changed_signal_emits_debounced_text(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    seen = []
    ed.content_changed.connect(seen.append)
    with qtbot.waitSignal(ed.content_changed, timeout=1000):
        ed.setPlainText("# hello")
    assert seen and seen[-1] == "# hello"


def test_editor_dropped_markdown_helper_only_md(qtbot, tmp_path):
    # 편집기 드롭은 .md/.markdown 파일 URL 만 가로챈다(그 외는 기존 텍스트 동작 유지).
    from PySide6.QtCore import QMimeData, QUrl
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    md = tmp_path / "x.md"; md.write_text("x", encoding="utf-8")
    txt = tmp_path / "x.txt"; txt.write_text("x", encoding="utf-8")
    m_md = QMimeData(); m_md.setUrls([QUrl.fromLocalFile(str(md))])
    m_txt = QMimeData(); m_txt.setUrls([QUrl.fromLocalFile(str(txt))])
    m_none = QMimeData(); m_none.setText("just text")
    assert MarkdownEditor._dropped_markdown(m_md) == md
    assert MarkdownEditor._dropped_markdown(m_txt) is None
    assert MarkdownEditor._dropped_markdown(m_none) is None


def test_editor_md_drop_emits_open_request(qtbot, tmp_path):
    # .md 드롭 → file_open_requested(Path) 발화(편집기 텍스트에 경로가 끼지 않음).
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDropEvent
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    md = tmp_path / "drop.md"; md.write_text("DROPPED", encoding="utf-8")
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(md))])
    ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier)
    got = []
    ed.file_open_requested.connect(lambda p: got.append(p))
    ed.dropEvent(ev)
    assert got == [md]
    assert ed.toPlainText() == ""        # 경로 텍스트가 끼어들지 않음
