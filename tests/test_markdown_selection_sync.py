"""미리보기↔편집기 선택 범위 동기화 (source-line 매핑, 2026-05-29 사용자 요청).

방식(VS Code/Joplin): 렌더 HTML 블록에 data-source-line(원문 줄) 주입 → 줄 매핑으로
'어느 줄'인지 정확히 알고(중복 단어 구분), 그 줄 구간 안에서 선택 텍스트로 글자 단위
정밀화. 못 찾으면 줄 전체 선택.

WebEngine JS(selectionchange 캡처/줄강조)는 헤드리스 미검증 — 사용자 실측. 여기서는
매핑 로직 + 시그널 배선(편집기↔preview)을 Fallback/시그널로 검증.
"""
from __future__ import annotations

from PySide6.QtGui import QTextCursor


def _tab(qtbot, text: str):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText(text)
    return tab


# ---------- 미리보기 → 편집기 ----------
def test_preview_selection_selects_matching_editor_text(qtbot):
    tab = _tab(qtbot, "# 제목\n\n본문 foo bar")
    tab.preview.selection_changed.emit(2, 2, "foo")     # 줄 2에서 'foo' 선택
    assert tab.editor.textCursor().selectedText() == "foo"


def test_source_line_disambiguates_duplicate_words(qtbot):
    # 'foo' 가 줄 0,2 두 번 — 줄 매핑이 어느 것인지 정확히 집어준다(naive find 의 약점 보완).
    tab = _tab(qtbot, "foo one\n\nfoo two")
    tab.preview.selection_changed.emit(2, 2, "foo")     # 줄 2의 foo
    cur = tab.editor.textCursor()
    assert cur.selectedText() == "foo"
    # 줄 2의 foo 위치(두 번째)인지 확인 — selectionStart 가 줄0의 0이 아니라 줄2 시작 이상
    line2_start = tab.editor.document().findBlockByNumber(2).position()
    assert cur.selectionStart() >= line2_start


def test_preview_selection_falls_back_to_whole_line(qtbot):
    # 렌더 '굵게 강조' 는 raw '**굵게** 강조' 에 그대로 없음 → 줄 전체 선택으로 폴백.
    tab = _tab(qtbot, "**굵게** 강조")
    tab.preview.selection_changed.emit(0, 0, "굵게 강조")
    assert tab.editor.textCursor().selectedText() == "**굵게** 강조"


def test_preview_clear_selection(qtbot):
    tab = _tab(qtbot, "본문 foo")
    tab.preview.selection_changed.emit(-1, -1, "")      # 해제 신호
    assert tab._last_preview_sel is None


def test_preview_deselect_clears_editor_selection(qtbot):
    # 회귀(사용자 2026-05-29): 미리보기에서 선택 취소하면 편집기 선택도 풀려야 함(대칭).
    tab = _tab(qtbot, "# 제목\n\n본문 foo bar")
    tab.preview.selection_changed.emit(2, 2, "foo")     # 미리보기 선택 → 편집기 선택됨
    assert tab.editor.textCursor().selectedText() == "foo"
    tab.preview.selection_changed.emit(-1, -1, "")      # 미리보기 선택 취소(KSELCLEAR)
    assert not tab.editor.textCursor().hasSelection()   # 편집기 선택도 해제


# ---------- 편집기 → 미리보기 ----------
def test_editor_selection_highlights_preview_lines(qtbot):
    tab = _tab(qtbot, "line0\nline1\nline2\nline3")
    calls: list[tuple[int, int]] = []
    tab.preview.highlight_source_lines = lambda s, e: calls.append((s, e))
    doc = tab.editor.document()
    cur = tab.editor.textCursor()
    cur.setPosition(doc.findBlockByNumber(1).position())
    cur.setPosition(doc.findBlockByNumber(2).position() + 2, QTextCursor.KeepAnchor)
    tab.editor.setTextCursor(cur)
    assert calls and calls[-1] == (1, 2)


def test_editor_deselect_clears_preview(qtbot):
    # 선택했다가 해제하면 미리보기 강조가 풀려야 함 (selectionChanged 는 선택이 실제로
    # 바뀔 때만 발화 — 선택→해제 전환에서 clear 호출).
    tab = _tab(qtbot, "line0\nline1\nline2")
    cleared: list[bool] = []
    tab.preview.highlight_source_lines = lambda s, e: None
    tab.preview.clear_source_highlight = lambda: cleared.append(True)
    cur = tab.editor.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.KeepAnchor)   # 선택 생성
    tab.editor.setTextCursor(cur)
    cur2 = tab.editor.textCursor()
    cur2.clearSelection()                        # 선택 해제
    tab.editor.setTextCursor(cur2)
    assert cleared


# ---------- 모드 전환 유지 (C1) ----------
def test_preview_selection_persists_into_editor_mode(qtbot):
    from screen_recorder.ui.markdown_tab import ViewMode
    tab = _tab(qtbot, "# 제목\n\n본문 foo bar")
    tab.set_view_mode(ViewMode.PREVIEW)
    tab.preview.selection_changed.emit(2, 2, "foo")     # 미리보기에서 선택
    tab.set_view_mode(ViewMode.EDITOR)                  # 편집 모드로 전환
    assert tab.editor.textCursor().selectedText() == "foo"   # 선택 유지


def test_preview_selection_consumed_once(qtbot):
    # 회귀(advisor): 모드 전환마다 옛 미리보기 선택이 재적용되면 안 됨 — 한 번만 유지.
    from screen_recorder.ui.markdown_tab import ViewMode
    tab = _tab(qtbot, "# 제목\n\n본문 foo bar")
    tab.set_view_mode(ViewMode.PREVIEW)
    tab.preview.selection_changed.emit(2, 2, "foo")
    tab.set_view_mode(ViewMode.EDITOR)
    assert tab.editor.textCursor().selectedText() == "foo"
    assert tab._last_preview_sel is None                # 소비됨
    cur = tab.editor.textCursor()                       # 사용자가 커서를 다른 데로
    cur.clearSelection()
    cur.setPosition(0)
    tab.editor.setTextCursor(cur)
    tab.set_view_mode(ViewMode.PREVIEW)
    tab.set_view_mode(ViewMode.EDITOR)                  # 다시 와도 옛 선택 재적용 X
    assert not tab.editor.textCursor().hasSelection()


# ---------- 루프 방지 ----------
def test_no_echo_loop_preview_to_editor(qtbot):
    tab = _tab(qtbot, "# t\n\n본문 foo")
    calls: list[tuple[int, int]] = []
    tab.preview.highlight_source_lines = lambda s, e: calls.append((s, e))
    tab.preview.selection_changed.emit(2, 2, "foo")     # 편집기 선택 적용(가드 중)
    assert calls == []                                  # 편집기→미리보기 에코 없음
