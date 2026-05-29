"""편집기 가운데 버튼 autoscroll + 미리보기 검색 하이라이트 (2026-05-29 사용자 요청).

- 가운데(휠) 버튼을 누르면 미리보기(Chromium)처럼 연속 스크롤(autoscroll) — 커서를
  anchor 에서 멀리 둘수록 그 방향으로 계속 이동, 다시 누르면 종료.
- 검색하면 편집기뿐 아니라 미리보기에서도 같은 단어가 강조됨.
  (conftest KSTUDIO_DISABLE_WEBENGINE=1 → 미리보기는 Fallback QTextBrowser 로 검증.
   WebEngine findText 경로는 헤드리스 미검증 — 사용자 재시작 확인 필요.)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent


def _press(ed, pt, button):
    ed.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*pt), button, button, Qt.NoModifier))


# ---------- 가운데 버튼 autoscroll ----------
def test_middle_button_starts_and_toggles_autoscroll(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("\n".join(f"line {i} aaaa bbbb" for i in range(300)))
    ed.setFixedSize(200, 100)
    ed.show()
    qtbot.waitUntil(lambda: ed.verticalScrollBar().maximum() > 50, timeout=2000)
    _press(ed, (100, 50), Qt.MiddleButton)
    assert ed._autoscrolling is True
    _press(ed, (100, 50), Qt.MiddleButton)   # 다시 누르면 토글 OFF
    assert ed._autoscrolling is False


def test_autoscroll_follows_cursor_direction(qtbot):
    # 커서를 anchor 아래·오른쪽에 두면 그 방향(viewport-follow)으로 연속 스크롤.
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("\n".join(f"line {i} aaaaaaaaaaaa bbbbbbbbbbbb" for i in range(300)))
    ed.setFixedSize(200, 100)
    ed.show()
    qtbot.waitUntil(lambda: ed.verticalScrollBar().maximum() > 50, timeout=2000)
    _press(ed, (100, 50), Qt.MiddleButton)
    ed._autoscroll_anchor = QPoint(100, 50)
    ed._autoscroll_pos = QPoint(140, 90)     # 오른쪽 40 · 아래 40 (deadzone 초과)
    vsb, hsb = ed.verticalScrollBar(), ed.horizontalScrollBar()
    v0, h0 = vsb.value(), hsb.value()
    ed._autoscroll_tick()
    assert vsb.value() > v0                   # 아래로
    if hsb.maximum() > 0:
        assert hsb.value() > h0               # 오른쪽으로


def test_autoscroll_deadzone_no_move(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("\n".join(f"line {i}" for i in range(300)))
    ed.setFixedSize(200, 100)
    ed.show()
    qtbot.waitUntil(lambda: ed.verticalScrollBar().maximum() > 50, timeout=2000)
    _press(ed, (100, 50), Qt.MiddleButton)
    ed._autoscroll_anchor = QPoint(100, 50)
    ed._autoscroll_pos = QPoint(105, 55)     # deadzone(12) 안 → 스크롤 X
    vsb = ed.verticalScrollBar()
    v0 = vsb.value()
    ed._autoscroll_tick()
    assert vsb.value() == v0


def test_left_button_no_autoscroll(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("hello world")
    ed.show()
    _press(ed, (10, 10), Qt.LeftButton)
    assert ed._autoscrolling is False


# ---------- 미리보기 검색 하이라이트 ----------
def _browser(pv):
    return pv._renderer.widget()


def test_preview_highlight_marks_all_matches(qtbot):
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    pv.set_content("# 제목\nfoo bar foo baz foo", None)
    pv.highlight_search("foo")
    assert len(_browser(pv).extraSelections()) == 3


def test_preview_highlight_empty_clears(qtbot):
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    pv.set_content("foo foo", None)
    pv.highlight_search("foo")
    assert len(_browser(pv).extraSelections()) == 2
    pv.highlight_search("")
    assert len(_browser(pv).extraSelections()) == 0


def test_preview_highlight_case_sensitive(qtbot):
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    pv.set_content("Foo foo FOO", None)
    pv.highlight_search("foo", case=False)
    assert len(_browser(pv).extraSelections()) == 3
    pv.highlight_search("foo", case=True)
    assert len(_browser(pv).extraSelections()) == 1


def test_preview_highlight_survives_rerender(qtbot):
    """편집하며 검색 중 — 본문이 다시 렌더돼도 하이라이트가 복원돼야 함."""
    from screen_recorder.ui.markdown.preview import MarkdownPreview
    pv = MarkdownPreview()
    qtbot.addWidget(pv)
    pv.set_content("foo foo", None)
    pv.highlight_search("foo")
    pv.set_content("foo foo foo", None)   # 재렌더
    assert len(_browser(pv).extraSelections()) == 3


def test_search_bar_drives_preview_highlight(qtbot):
    """탭 통합: 검색 바에 입력하면 미리보기에도 하이라이트가 적용된다."""
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("alpha beta alpha")
    tab._refresh_preview("alpha beta alpha")   # 디바운스 우회 — 미리보기 즉시 갱신
    tab._search_bar.open_find()
    tab._search_bar.set_query("alpha")
    assert len(_browser(tab.preview).extraSelections()) == 2
    tab._search_bar.close_bar()
    assert len(_browser(tab.preview).extraSelections()) == 0   # 닫으면 해제
