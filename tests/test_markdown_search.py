"""Markdown 찾기/바꾸기 — 에디터 기준 검색, 미리보기는 위치만 따라감(사용자 결정 2026-05-29).

검색 엔진은 에디터(QPlainTextEdit)만 다루므로 WebEngine 불필요 → 헤드리스로 전부 검증 가능.
"""
from screen_recorder.ui.markdown.editor import MarkdownEditor
from screen_recorder.ui.markdown.search_bar import MarkdownSearchBar


def _bar(qtbot, text):
    ed = MarkdownEditor()
    ed.setPlainText(text)
    qtbot.addWidget(ed)
    bar = MarkdownSearchBar(ed)
    qtbot.addWidget(bar)
    return ed, bar


def test_find_counts_all_matches(qtbot):
    ed, bar = _bar(qtbot, "foo foo bar foo")
    bar.set_query("foo")
    assert bar.match_count() == 3
    assert bar.current_index() == 0


def test_find_next_and_prev_wrap(qtbot):
    ed, bar = _bar(qtbot, "a x a x a")
    bar.set_query("a")
    assert bar.current_index() == 0
    bar.find_next(); assert bar.current_index() == 1
    bar.find_next(); assert bar.current_index() == 2
    bar.find_next(); assert bar.current_index() == 0   # wrap forward
    bar.find_prev(); assert bar.current_index() == 2   # wrap backward


def test_case_insensitive_default_then_toggle(qtbot):
    ed, bar = _bar(qtbot, "Foo foo FOO")
    bar.set_query("foo")
    assert bar.match_count() == 3
    bar.set_case_sensitive(True)
    assert bar.match_count() == 1


def test_no_match_is_safe(qtbot):
    ed, bar = _bar(qtbot, "hello world")
    bar.set_query("zzz")
    assert bar.match_count() == 0
    assert bar.current_index() == -1
    bar.find_next()   # no crash
    bar.find_prev()
    assert bar.current_index() == -1


def test_replace_current_only_one(qtbot):
    ed, bar = _bar(qtbot, "foo foo")
    bar.set_query("foo")
    bar.set_replacement("baz")
    bar.replace_current()
    assert "baz" in ed.toPlainText()
    assert ed.toPlainText().count("foo") == 1


def test_replace_all_is_single_undo(qtbot):
    ed, bar = _bar(qtbot, "foo foo foo")
    bar.set_query("foo")
    bar.set_replacement("X")
    n = bar.replace_all()
    assert n == 3
    assert ed.toPlainText() == "X X X"
    ed.undo()
    assert ed.toPlainText() == "foo foo foo"   # 한 번에 원복


def test_close_clears_highlights(qtbot):
    ed, bar = _bar(qtbot, "foo foo")
    bar.set_query("foo")
    assert len(ed.extraSelections()) == 2
    bar.close_bar()
    assert ed.extraSelections() == []


def test_empty_query_clears(qtbot):
    ed, bar = _bar(qtbot, "foo")
    bar.set_query("foo")
    assert bar.match_count() == 1
    bar.set_query("")
    assert bar.match_count() == 0
    assert ed.extraSelections() == []


def test_tab_ctrl_f_path_wires_search(qtbot):
    # MarkdownTab 통합: 검색 바가 붙고 open_find 로 열리며 에디터를 검색한다.
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("alpha beta alpha")
    assert tab._search_bar is not None
    # 부모 탭을 show 하지 않은 헤드리스라 isVisible()(조상 의존) 대신 isHidden()(명시 플래그)로 검증.
    assert tab._search_bar.isHidden()
    tab._search_bar.open_find()
    assert not tab._search_bar.isHidden()
    tab._search_bar.set_query("alpha")
    assert tab._search_bar.match_count() == 2
