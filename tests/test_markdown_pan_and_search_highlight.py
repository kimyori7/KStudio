"""편집기 가운데 버튼 hand-pan + 미리보기 검색 하이라이트 (2026-05-29 사용자 요청).

- 가운데(휠) 버튼을 누른 채 끌면 상하좌우로 내용이 이동.
- 검색하면 편집기뿐 아니라 미리보기에서도 같은 단어가 강조됨.
  (conftest KSTUDIO_DISABLE_WEBENGINE=1 → 미리보기는 Fallback QTextBrowser 로 검증.
   WebEngine findText 경로는 헤드리스 미검증 — 사용자 재시작 확인 필요.)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent


# ---------- 가운데 버튼 hand-pan ----------
def test_middle_button_drag_pans(qtbot):
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("\n".join(
        f"line {i} aaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbb" for i in range(300)))
    ed.setFixedSize(200, 100)
    ed.show()
    qtbot.waitUntil(lambda: ed.verticalScrollBar().maximum() > 50, timeout=2000)
    vsb = ed.verticalScrollBar()
    vsb.setValue(120)
    v0 = vsb.value()

    def mouse(kind, pt, button, buttons):
        ed_method = {
            "press": ed.mousePressEvent,
            "move": ed.mouseMoveEvent,
            "release": ed.mouseReleaseEvent,
        }[kind]
        ev_type = {
            "press": QEvent.Type.MouseButtonPress,
            "move": QEvent.Type.MouseMove,
            "release": QEvent.Type.MouseButtonRelease,
        }[kind]
        ed_method(QMouseEvent(ev_type, QPointF(*pt), button, buttons, Qt.NoModifier))

    mouse("press", (50, 50), Qt.MiddleButton, Qt.MiddleButton)
    assert ed._panning is True
    mouse("move", (50, 20), Qt.NoButton, Qt.MiddleButton)   # 위로 30 끌기
    assert vsb.value() == v0 + 30                            # 내용이 위로 → 값 증가
    mouse("release", (50, 20), Qt.MiddleButton, Qt.NoButton)
    assert ed._panning is False


def test_left_button_does_not_pan(qtbot):
    """좌클릭은 pan 모드 진입 안 함 (텍스트 선택 정상)."""
    from screen_recorder.ui.markdown.editor import MarkdownEditor
    ed = MarkdownEditor()
    qtbot.addWidget(ed)
    ed.setPlainText("hello world")
    ed.show()
    ed.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(10, 10),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert ed._panning is False


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
