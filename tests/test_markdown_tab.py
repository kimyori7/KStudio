def test_from_file_reads_utf8(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "a.md"
    p.write_text("# 제목\n본문", encoding="utf-8")
    tab = MarkdownTab.from_file(p)
    qtbot.addWidget(tab)
    assert tab.editor.toPlainText() == "# 제목\n본문"
    assert tab.saved_path() == p
    assert tab.needs_save() is False
    assert tab.source_label() == "opened"


def test_edit_sets_dirty_and_emits(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")
    tab = MarkdownTab.from_file(p)
    qtbot.addWidget(tab)
    with qtbot.waitSignal(tab.save_state_changed, timeout=1000):
        tab.editor.setPlainText("x changed")
    assert tab.needs_save() is True


def test_save_writes_utf8_and_clears_dirty(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "a.md"
    p.write_text("x", encoding="utf-8")
    tab = MarkdownTab.from_file(p)
    qtbot.addWidget(tab)
    tab.editor.setPlainText("새 내용")
    assert tab.save() is True
    assert p.read_text(encoding="utf-8") == "새 내용"
    assert tab.needs_save() is False


def test_from_blank_needs_save(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    assert tab.saved_path() is None
    assert tab.needs_save() is True
    assert tab.source_label() == "new"


def test_open_cp949_fallback(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "legacy.md"
    p.write_bytes("# 한글".encode("cp949"))
    tab = MarkdownTab.from_file(p)  # utf-8 실패 → cp949 폴백
    qtbot.addWidget(tab)
    assert "한글" in tab.editor.toPlainText()


def test_view_mode_toggle_visibility(qtbot):
    from screen_recorder.ui.markdown_tab import MarkdownTab, ViewMode
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.show()
    tab.set_view_mode(ViewMode.EDITOR)
    assert tab.editor.isVisible() and not tab.preview.isVisible()
    tab.set_view_mode(ViewMode.PREVIEW)
    assert tab.preview.isVisible() and not tab.editor.isVisible()
    tab.set_view_mode(ViewMode.SPLIT)
    assert tab.editor.isVisible() and tab.preview.isVisible()
