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
    from screen_recorder.ui.markdown_tab import SaveResult
    tab.editor.setPlainText("새 내용")
    assert tab.save() is SaveResult.SAVED
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


def test_save_failure_does_not_corrupt_saved_path(qtbot, tmp_path, monkeypatch):
    # 회귀 (리뷰 #4): 쓰기 실패 시 _saved_path 가 갱신되면 안 됨 (성공 시에만 mark_saved).
    import pathlib
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("내용")
    target = tmp_path / "out.md"

    def boom(self, *a, **k):
        raise OSError("disk full")

    from screen_recorder.ui.markdown_tab import SaveResult
    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    assert tab.save_as(target) is SaveResult.FAILED
    assert tab.saved_path() is None      # 실패 시 경로 미갱신
    assert tab.needs_save() is True


def test_save_as_cancel_returns_cancelled(qtbot, monkeypatch):
    # 회귀 (검증 워크플로 #4): 다이얼로그 취소는 FAILED 가 아니라 CANCELLED — 경고 X.
    from screen_recorder.ui import markdown_tab as M
    from screen_recorder.ui.markdown_tab import MarkdownTab, SaveResult
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    monkeypatch.setattr(M.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    assert tab.save_as() is SaveResult.CANCELLED
    assert tab.saved_path() is None
