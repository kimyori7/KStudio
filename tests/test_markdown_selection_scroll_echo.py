"""선택 동기화가 미리보기 스크롤을 건드리면 안 된다 (2026-07-22 사용자 보고).

증상: 미리보기에서 드래그로 영역 지정 → 취소 → 같은 문서의 다른 위치로 스크롤 →
거기서 다시 드래그하려 하면 화면이 *앞서 선택했던 위치*로 튄다.

원인(에코 루프): 선택 동기화는 편집기 커서를 옮기는데, `setTextCursor` 와
`ensureCursorVisible` 은 그 커서를 보이게 하려고 **편집기를 스크롤한다**. 그 스크롤이
`_on_editor_scrolled` → `preview.set_scroll_ratio` 로 되돌아와 사용자가 드래그 중인
미리보기를 통째로 끌고 간다. `_on_editor_scrolled` 의 가드가 `_syncing`(스크롤 루프)
뿐이라 `_sel_syncing`(선택 루프) 경로가 그대로 새어 나갔다.

'하필 이전 선택 위치'인 이유: 미리보기를 스크롤해도 편집기 *커서*는 옛 선택 자리에
남는다. 새 드래그의 mousedown 이 브라우저 선택을 무너뜨리며 KSELCLEAR 를 보내면
파이썬은 그 옛 커서로 `setTextCursor` 를 부르고, 편집기가 옛 자리로 스크롤하면서
그 비율이 미리보기로 되돌아온다.
"""
from __future__ import annotations


def _scrollable_tab(qtbot):
    """진짜 스크롤 범위를 가진 탭 — 충분한 줄 + 작은 고정 높이 (test_markdown_tab 패턴)."""
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("\n".join(f"line {i}" for i in range(300)))
    tab.editor.setFixedSize(200, 80)
    tab.show()
    qtbot.waitUntil(lambda: tab.editor.verticalScrollBar().maximum() > 0, timeout=2000)
    return tab


def test_preview_selection_does_not_scroll_preview(qtbot):
    """미리보기에서 새로 드래그 선택해도 미리보기 스크롤 명령이 나가면 안 된다."""
    tab = _scrollable_tab(qtbot)
    vsb = tab.editor.verticalScrollBar()
    tab._on_preview_scrolled(0.9)            # 사용자가 미리보기를 아래로 스크롤
    before = vsb.value()

    calls: list[float] = []
    tab.preview.set_scroll_ratio = lambda r: calls.append(r)
    tab.preview.selection_changed.emit(5, 5, "line 5")   # 위쪽 줄을 새로 드래그 선택
    qtbot.wait(50)   # 가드 해제 *후* 뒤늦게 새는 스크롤(지연 재배치)도 잡는다

    # 전제: 편집기가 실제로 스크롤됐어야 이 테스트가 에코 경로를 지난다.
    # (안 움직였으면 통과해도 의미 없음 — 빈 테스트 방지.)
    assert vsb.value() != before, "편집기가 안 움직였다 — 에코 경로를 못 탄 무의미한 통과"
    assert calls == [], f"드래그 중 미리보기가 강제 스크롤됨: {calls}"


def test_preview_deselect_does_not_scroll_preview_back(qtbot):
    """사용자가 겪은 그 순서 — 선택 → 스크롤 → 새 드래그의 mousedown(KSELCLEAR).

    옛 커서가 남아 있어 `setTextCursor` 가 편집기를 옛 자리로 되돌리는데, 그 비율이
    미리보기로 새어 나가면 화면이 '이전에 선택했던 곳'으로 튄다.
    """
    tab = _scrollable_tab(qtbot)
    vsb = tab.editor.verticalScrollBar()
    tab.preview.selection_changed.emit(5, 5, "line 5")   # ① 위쪽에서 영역 지정
    tab._on_preview_scrolled(0.9)                        # ② 아래로 스크롤 (커서는 줄 5)
    before = vsb.value()

    calls: list[float] = []
    tab.preview.set_scroll_ratio = lambda r: calls.append(r)
    tab.preview.selection_changed.emit(-1, -1, "")       # ③ 새 드래그 mousedown
    qtbot.wait(50)   # 가드 해제 *후* 뒤늦게 새는 스크롤(지연 재배치)도 잡는다

    assert vsb.value() != before, "편집기가 안 움직였다 — 에코 경로를 못 탄 무의미한 통과"
    assert calls == [], f"미리보기가 이전 선택 위치로 끌려감: {calls}"


def test_user_scroll_still_drives_preview(qtbot):
    """가드가 과하면 안 된다 — 사용자가 편집기를 스크롤하는 정상 동기화는 살아 있어야."""
    tab = _scrollable_tab(qtbot)
    calls: list[float] = []
    tab.preview.set_scroll_ratio = lambda r: calls.append(r)
    vsb = tab.editor.verticalScrollBar()
    vsb.setValue(vsb.maximum())
    assert calls and abs(calls[-1] - 1.0) < 1e-6
