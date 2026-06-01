"""문서 비교(DIFF) 뷰 — 순수 코어 + 패널 색칠 + 뷰 채움/재계산 (2026-05-29).

compute_diff 는 Qt 비의존 순수 함수라 줄/글자 마크를 직접 단언한다. DiffPane 의 색칠은
extraSelections 로 실제 적용되므로 헤드리스에서 결과를 조회해 검증(WebEngine 과 달리 가능).
"""
from __future__ import annotations

from screen_recorder.ui.markdown.diff_view import (
    CharMark, DiffPane, DiffView, LineMark, SideMarks, compute_diff,
)


def _line_kinds(side: SideMarks) -> set[tuple[int, str]]:
    return {(m.line, m.kind) for m in side.lines}


# ---------- 순수 코어 ----------
def test_identical_no_marks():
    l, r = compute_diff("a\nb\nc", "a\nb\nc")
    assert l.lines == [] and r.lines == []
    assert l.chars == [] and r.chars == []


def test_pure_insertion_marks_right_added():
    l, r = compute_diff("a\nc", "a\nb\nc")
    assert _line_kinds(r) == {(1, "added")}
    assert l.lines == []


def test_pure_deletion_marks_left_deleted():
    l, r = compute_diff("a\nb\nc", "a\nc")
    assert _line_kinds(l) == {(1, "deleted")}
    assert r.lines == []


def test_replace_marks_changed_both_sides_with_char_ranges():
    # 'cat' -> 'cot': 줄0 changed 양쪽, 글자 1번(a/o)이 char 마크.
    l, r = compute_diff("cat", "cot")
    assert _line_kinds(l) == {(0, "changed")}
    assert _line_kinds(r) == {(0, "changed")}
    assert any(c.line == 0 and c.start <= 1 < c.end for c in l.chars)
    assert any(c.line == 0 and c.start <= 1 < c.end for c in r.chars)


def test_empty_side_marks_all_added():
    l, r = compute_diff("", "a\nb")
    assert l.lines == []
    assert _line_kinds(r) == {(0, "added"), (1, "added")}


# ---------- 패널 색칠 ----------
def test_diffpane_applies_extra_selections(qtbot):
    pane = DiffPane()
    qtbot.addWidget(pane)
    pane.setPlainText("cat\ndog")
    pane.apply_marks(SideMarks(lines=[LineMark(0, "changed")],
                               chars=[CharMark(0, 1, 2)]))
    sels = pane.extraSelections()
    assert len(sels) == 2          # 줄 1 + 글자 1


def test_diffpane_clear_marks(qtbot):
    pane = DiffPane()
    qtbot.addWidget(pane)
    pane.setPlainText("a")
    pane.apply_marks(SideMarks(lines=[LineMark(0, "added")]))
    assert pane.extraSelections()
    pane.apply_marks(SideMarks())
    assert pane.extraSelections() == []


def test_diffpane_drop_accepts_only_markdown(qtbot, tmp_path):
    from PySide6.QtCore import QUrl, QMimeData
    pane = DiffPane()
    qtbot.addWidget(pane)
    md = tmp_path / "x.md"; md.write_text("x", encoding="utf-8")
    png = tmp_path / "x.png"; png.write_bytes(b"\x89PNG")
    m_ok = QMimeData(); m_ok.setUrls([QUrl.fromLocalFile(str(md))])
    m_no = QMimeData(); m_no.setUrls([QUrl.fromLocalFile(str(png))])
    assert pane._accepted_path(m_ok) == md
    assert pane._accepted_path(m_no) is None


# ---------- 뷰 ----------
def test_diffview_recompute_colors_both_panes(qtbot):
    v = DiffView()
    qtbot.addWidget(v)
    v.left.setPlainText("cat\nsame")
    v.right.setPlainText("cot\nsame")
    v._recompute()
    assert v.left.extraSelections()
    assert v.right.extraSelections()


def test_diffview_fill_next_left_then_right(qtbot, tmp_path):
    a = tmp_path / "a.md"; a.write_text("AAA", encoding="utf-8")
    b = tmp_path / "b.md"; b.write_text("BBB", encoding="utf-8")
    v = DiffView()
    qtbot.addWidget(v)
    v.fill_next(a)                       # 왼쪽 비어있음 → 왼쪽
    assert v.left.toPlainText() == "AAA"
    v.fill_next(b)                       # 왼쪽 찼음 → 오른쪽
    assert v.right.toPlainText() == "BBB"
    assert v.right_path == b
    assert v.has_empty_pane() is False


def test_diffview_right_edit_sets_dirty(qtbot):
    v = DiffView()
    qtbot.addWidget(v)
    assert v.right_dirty is False
    v.right.setPlainText("typed")        # 오른쪽 편집 → dirty
    assert v.right_dirty is True


# ---------- MarkdownTab 배선 ----------
def _tab(qtbot, text=""):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    if text:
        tab.editor.setPlainText(text)
    return tab


def test_diff_mode_shares_document(qtbot):
    from screen_recorder.ui.markdown_tab import ViewMode
    tab = _tab(qtbot, "hello")
    tab.set_view_mode(ViewMode.DIFF)
    # 왼쪽 패널 = 탭 문서 공유 → 같은 텍스트.
    assert tab._diff_view.left.toPlainText() == "hello"
    # 왼쪽에서 고치면 탭 editor 에도 반영(동일 document).
    tab._diff_view.left.setPlainText("world")
    assert tab.editor.toPlainText() == "world"


def test_diff_button_switches_mode(qtbot):
    from screen_recorder.ui.markdown_tab import ViewMode
    tab = _tab(qtbot, "x")
    tab.set_view_mode(ViewMode.DIFF)
    assert tab._diff_view is not None and tab._diff_view.isVisibleTo(tab)
    assert not tab._splitter.isVisibleTo(tab)
    tab.set_view_mode(ViewMode.EDITOR)   # 돌아오면 diff 숨고 splitter 복귀
    assert not tab._diff_view.isVisibleTo(tab)
    assert tab._splitter.isVisibleTo(tab)


def test_diff_right_dirty_marks_needs_save(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import ViewMode
    tab = _tab(qtbot, "left text")
    tab.mark_saved(tmp_path / "f.md")    # 깨끗한 저장 상태 → needs_save False
    assert tab.needs_save() is False
    tab.set_view_mode(ViewMode.DIFF)
    tab._diff_view.right.setPlainText("compare")   # 오른쪽 편집 → dirty
    assert tab.needs_save() is True


def test_diff_fill_routing_empty_pane(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import ViewMode
    b = tmp_path / "b.md"; b.write_text("BBB", encoding="utf-8")
    tab = _tab(qtbot, "left text")        # 왼쪽 찼음(현재 문서)
    tab.set_view_mode(ViewMode.DIFF)
    assert tab.diff_has_empty_pane() is True       # 오른쪽 비어 있음
    tab.fill_diff_next(b)                          # 다음 빈 칸=오른쪽
    assert tab._diff_view.right.toPlainText() == "BBB"
    assert tab.diff_has_empty_pane() is False


def test_open_entry_routes_document_click_to_diff_fill(qtbot, tmp_path):
    # main_window 라우팅: 활성 탭이 DIFF+빈칸이면 라이브러리 문서 클릭이 탭을 열지 않고 채운다.
    from PySide6.QtGui import QImage
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import AppSettings
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui.markdown_tab import MarkdownTab, ViewMode
    b = tmp_path / "b.md"; b.write_text("ROUTED", encoding="utf-8")
    win = build_main_window(settings=AppSettings())
    qtbot.addWidget(win)
    tab = MarkdownTab.from_blank()
    tab.editor.setPlainText("left doc")
    win.tab_area.add_markdown(tab, entry_id=999, display_name="left")
    win.tab_area.setCurrentWidget(tab)
    tab.set_view_mode(ViewMode.DIFF)               # 왼쪽=현재문서, 오른쪽 빈칸
    e = win.library_model.add(EntryKind.DOCUMENT, thumbnail=QImage(),
                              source_label="b", display_name="b", path=b)
    win._open_entry(e.id)                          # 클릭 라우팅 → 오른쪽 채움
    assert tab._diff_view.right.toPlainText() == "ROUTED"
    win.close()
