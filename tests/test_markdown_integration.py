def test_open_path_md_creates_markdown_tab(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.markdown_tab import MarkdownTab
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    cur = win.tab_area.currentWidget()
    assert isinstance(cur, MarkdownTab)
    assert win.mode_controller.mode() is AppMode.DOCUMENT
    win.close()


def test_open_same_md_focuses_existing(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    first = win.tab_area.currentWidget()
    win._open_path(p)  # 두 번째 열기 → 같은 탭 포커스, 중복 생성 X
    assert win.tab_area.currentWidget() is first
    win.close()


def test_new_markdown_creates_blank_tab(qtbot):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.markdown_tab import MarkdownTab
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    win._on_new_markdown()
    cur = win.tab_area.currentWidget()
    assert isinstance(cur, MarkdownTab)
    assert win.mode_controller.mode() is AppMode.DOCUMENT
    win.close()


def test_markdown_mode_hides_tool_palette(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    p = tmp_path / "doc.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    # 문서 모드에선 이미지용 도구 팔레트·주석 툴바가 숨겨져야 함
    assert not win.tool_palette.isVisible()
    assert not win.annotation_toolbar.isVisible()
    win.close()
