"""ToolPalette 에 auto_trim 액션 버튼이 있고 클릭 시 action_triggered 발화."""
from __future__ import annotations


def test_auto_trim_action_button_exists_and_emits(qtbot):
    from screen_recorder.ui.tool_palette import ToolPalette
    pal = ToolPalette()
    qtbot.addWidget(pal)
    btn = pal.find_action_button("auto_trim")
    assert btn is not None
    assert not btn.isCheckable()   # one-shot 액션 — 토글 안 됨
    received = []
    pal.action_triggered.connect(received.append)
    btn.click()
    assert received == ["auto_trim"]
