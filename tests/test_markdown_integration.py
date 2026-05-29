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


def test_reopen_md_after_close(qtbot, tmp_path):
    # 회귀 (리뷰 #1): 닫은 .md 를 다시 열 수 있어야 함 (_markdown_paths stale eid 정리).
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.markdown_tab import MarkdownTab
    win = build_main_window()
    qtbot.addWidget(win)
    p = tmp_path / "a.md"
    p.write_text("# hi", encoding="utf-8")
    win._open_path(p)
    idx = win.tab_area.currentIndex()
    win.tab_area._on_close_requested(idx)   # 닫기 → entry_closed → _markdown_paths pop
    assert win.tab_area.count() == 0
    win._open_path(p)                        # 재오픈 — no-op 이면 안 됨
    assert isinstance(win.tab_area.currentWidget(), MarkdownTab)
    win.close()


def test_document_mode_button_no_tabs_does_not_open_screenshot(qtbot):
    # 회귀 (리뷰 #3): 문서 모드 버튼 클릭 시 탭 없으면 스크린샷을 열면 안 됨.
    from PySide6.QtGui import QImage
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    win.library_model.add(EntryKind.SCREENSHOT, thumbnail=img,
                          source_label="region", display_name="s.png")
    win._on_mode_button_clicked(AppMode.DOCUMENT)
    assert win.tab_area.count() == 0                       # 스크린샷 안 열림
    assert win.mode_controller.mode() is AppMode.DOCUMENT  # 모드 유지 (IMAGE 로 안 튐)
    win.close()
