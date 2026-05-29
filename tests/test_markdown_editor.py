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
