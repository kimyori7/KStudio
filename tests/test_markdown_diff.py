"""문서 비교(DIFF) 뷰 — 순수 코어 + 패널 색칠 + 뷰 채움/재계산 (2026-05-29).

compute_diff 는 Qt 비의존 순수 함수라 줄/글자 마크를 직접 단언한다. DiffPane 의 색칠은
extraSelections 로 실제 적용되므로 헤드리스에서 결과를 조회해 검증(WebEngine 과 달리 가능).
"""
from __future__ import annotations

from screen_recorder.ui.markdown.diff_view import (
    CharMark, DiffPane, DiffView, LineMark, SideMarks, compute_diff,
    overview_bands,
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


# ---------- 개요 띠(overview ruler) 순수 코어 ----------
def test_overview_bands_empty_when_total_zero():
    # 빈 문서(총 줄 0) → 0 나눗셈 없이 빈 띠.
    assert overview_bands(0, [LineMark(0, "added")], 100) == []


def test_overview_bands_empty_when_no_marks():
    assert overview_bands(10, [], 100) == []


def test_overview_bands_position_scales_to_height():
    # 10줄 중 5번째 줄 마크, 높이 100 → 절반 지점(y=50).
    bands = overview_bands(10, [LineMark(5, "changed")], 100)
    assert len(bands) == 1
    y, h, kind = bands[0]
    assert y == 50
    assert kind == "changed"


def test_overview_bands_min_height_for_single_line():
    # 100줄 중 1줄(높이 200이면 2px)이라도 최소 3px 로 보이게.
    bands = overview_bands(100, [LineMark(0, "deleted")], 200)
    assert bands[0][1] >= 3


def test_overview_bands_merges_contiguous_same_kind():
    # 연속된 같은 종류 줄(2~4 삭제)은 한 덩어리 띠로 합친다.
    bands = overview_bands(
        10, [LineMark(2, "deleted"), LineMark(3, "deleted"),
             LineMark(4, "deleted")], 100)
    assert len(bands) == 1
    y, h, kind = bands[0]
    assert kind == "deleted"
    assert y == 20 and h == 30      # 줄 2~4 → y=20, 끝=int(5/10*100)=50


def test_overview_bands_separates_on_gap_or_kind_change():
    bands = overview_bands(
        20, [LineMark(0, "deleted"), LineMark(10, "added")], 100)
    assert len(bands) == 2


def test_overview_bands_clamped_within_height():
    # 마지막 줄 마크가 바닥을 넘지 않도록 클램프(y+h <= height).
    bands = overview_bands(200, [LineMark(199, "added")], 100)
    y, h, _ = bands[0]
    assert y >= 0
    assert y + h <= 100


# ---------- 개요 띠 위젯 ----------
def test_overview_bar_click_left_half_targets_left(qtbot):
    from screen_recorder.ui.markdown.diff_view import DiffOverviewBar
    bar = DiffOverviewBar()
    qtbot.addWidget(bar)
    bar.resize(16, 100)
    side, ratio = bar._target_at(4, 50)      # 왼쪽 절반(x<8) → left, 중앙
    assert side == "left"
    assert abs(ratio - 0.5) < 0.02


def test_overview_bar_click_right_half_targets_right(qtbot):
    from screen_recorder.ui.markdown.diff_view import DiffOverviewBar
    bar = DiffOverviewBar()
    qtbot.addWidget(bar)
    bar.resize(16, 100)
    side, ratio = bar._target_at(12, 25)     # 오른쪽 절반(x>=8) → right
    assert side == "right"
    assert abs(ratio - 0.25) < 0.02


def test_overview_bar_emits_jump_on_click(qtbot):
    from PySide6.QtCore import QPoint, Qt
    from screen_recorder.ui.markdown.diff_view import DiffOverviewBar
    bar = DiffOverviewBar()
    qtbot.addWidget(bar)
    bar.resize(16, 100)
    bar.show()
    with qtbot.waitSignal(bar.jump, timeout=500) as blocker:
        qtbot.mouseClick(bar, Qt.LeftButton, pos=QPoint(4, 50))
    assert blocker.args[0] == "left"


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


def test_diffview_empty_side_clears_marks(qtbot):
    # 진입 직후(왼=문서, 오=빈칸): 비교 대상이 없으면 "전부 삭제"로 도배하지 않는다.
    v = DiffView()
    qtbot.addWidget(v)
    v.left.setPlainText("a\nb\nc\nd")
    v._recompute()                       # 오른쪽 빈칸
    assert v.left.extraSelections() == []
    assert v.overview._left_marks == []
    # 오른쪽을 채우면 정상적으로 diff 색이 돌아온다.
    v.right.setPlainText("a\nX\nc\nd")
    v._recompute()
    assert v.left.extraSelections()      # 이제 색칠됨


def test_diffview_overview_updates_on_recompute(qtbot):
    v = DiffView()
    qtbot.addWidget(v)
    v.left.setPlainText("a\nDELETED\nc")
    v.right.setPlainText("a\nc\nADDED")
    v._recompute()
    # 개요 띠가 좌/우 마크를 받음(왼쪽=삭제, 오른쪽=추가).
    assert v.overview._left_marks
    assert v.overview._right_marks


def test_diffview_overview_jump_scrolls_pane(qtbot):
    # 실제로 스크롤 가능한 긴 내용으로(빈 위젯은 스크롤 범위가 0이라 의미 없음).
    v = DiffView()
    qtbot.addWidget(v)
    v.resize(700, 300)
    v.right.setPlainText("\n".join(f"r{i}" for i in range(200)))
    v.show()
    qtbot.waitExposed(v)
    sb = v.right.verticalScrollBar()
    assert sb.maximum() > 0                   # 스크롤 분량이 실제로 있음
    v._on_overview_jump("right", 0.5)         # 50% 지점 → 최대치의 절반
    assert sb.value() == int(sb.maximum() * 0.5)


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


def _wired_diff_tab(qtbot, win, left_text=""):
    """main_window 에 배선된 MarkdownTab 을 DIFF 모드로 만들어 반환."""
    from screen_recorder.ui.markdown_tab import MarkdownTab, ViewMode
    tab = MarkdownTab.from_blank()
    if left_text:
        tab.editor.setPlainText(left_text)
    eid = win.library_model.next_id()
    win.tab_area.add_markdown(tab, entry_id=eid, display_name="left")
    win._wire_markdown_tab(tab)            # diff_doc_loaded / open_document_requested 연결
    win.tab_area.setCurrentWidget(tab)
    tab.set_view_mode(ViewMode.DIFF)
    return tab


def _entries_for(win, path):
    from pathlib import Path as _P
    return [x for x in win.library_model.entries()
            if x.path and _P(x.path).resolve() == _P(path).resolve()]


def test_diff_right_drop_registers_in_library(qtbot, tmp_path):
    # 오른쪽 칸에 파일을 올리면(드롭/파일창 동일 경로) 라이브러리에 DOCUMENT 로 등록.
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import AppSettings
    from screen_recorder.ui.library_model import EntryKind
    b = tmp_path / "cmp.md"; b.write_text("compare", encoding="utf-8")
    win = build_main_window(settings=AppSettings())
    qtbot.addWidget(win)
    tab = _wired_diff_tab(qtbot, win, left_text="left doc")
    tab._diff_view.load_side("right", b)   # 드롭 결과와 동일 경로
    matches = _entries_for(win, b)
    assert len(matches) == 1
    assert matches[0].kind is EntryKind.DOCUMENT
    tab._diff_view.load_side("right", b)   # 다시 올려도 중복 없음
    assert len(_entries_for(win, b)) == 1
    win.close()


def test_diff_left_drop_then_save_single_library_entry(qtbot, tmp_path):
    # advisor 함정: 빈 탭 왼쪽에 드롭 후 저장해도 같은 path 가 정확히 1개여야 함.
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import AppSettings
    a = tmp_path / "left.md"; a.write_text("LEFTDOC", encoding="utf-8")
    win = build_main_window(settings=AppSettings())
    qtbot.addWidget(win)
    tab = _wired_diff_tab(qtbot, win)      # 빈 탭
    tab._diff_view.load_side("left", a)    # 왼쪽(빈 탭)에 드롭
    win._on_file_save()                    # Ctrl+S 경로
    assert len(_entries_for(win, a)) == 1
    win.close()


def test_editor_md_drop_opens_and_registers(qtbot, tmp_path):
    # 편집 모드 편집기에 .md 드롭 → 새 문서 탭으로 열리고 라이브러리 등록.
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDropEvent
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import AppSettings
    c = tmp_path / "dropped.md"; c.write_text("DROPPED", encoding="utf-8")
    win = build_main_window(settings=AppSettings())
    qtbot.addWidget(win)
    win._on_new_markdown()                 # 배선된 빈 문서 탭(편집 모드)
    tab = win.tab_area.currentWidget()
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(c))])
    ev = QDropEvent(QPointF(8, 8), Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier)
    tab.editor.dropEvent(ev)
    assert len(_entries_for(win, c)) == 1
    win.close()


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
