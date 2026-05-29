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


def _make_scrollable_tab(qtbot):
    # 실제 스크롤 가능한 에디터 — QPlainTextEdit 는 내용 기반으로 스크롤 범위를 재계산하므로
    # setRange 수동 설정 대신 충분한 줄 + 작은 고정 높이로 진짜 범위를 만든다.
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("\n".join(f"line {i}" for i in range(300)))
    tab.editor.setFixedSize(200, 80)
    tab.show()
    qtbot.waitUntil(lambda: tab.editor.verticalScrollBar().maximum() > 0, timeout=2000)
    return tab


def test_editor_scroll_drives_preview(qtbot):
    # 에디터를 끝까지 스크롤하면 미리보기도 같은 비율(1.0)로 이동 요청.
    tab = _make_scrollable_tab(qtbot)
    calls = []
    tab.preview.set_scroll_ratio = lambda r: calls.append(r)
    vsb = tab.editor.verticalScrollBar()
    vsb.setValue(vsb.maximum())          # 100% → _on_editor_scrolled → ratio 1.0
    assert calls and abs(calls[-1] - 1.0) < 1e-6


def test_scroll_sync_no_infinite_loop(qtbot):
    # 미리보기→에디터 동기화가 다시 에디터→미리보기 echo 를 유발하면 안 됨 (_syncing 가드).
    tab = _make_scrollable_tab(qtbot)
    vsb = tab.editor.verticalScrollBar()
    calls = []
    tab.preview.set_scroll_ratio = lambda r: calls.append(r)
    tab._on_preview_scrolled(0.5)
    assert calls == []                                   # echo 차단됨
    assert vsb.value() == round(0.5 * vsb.maximum())     # 에디터는 이동


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
