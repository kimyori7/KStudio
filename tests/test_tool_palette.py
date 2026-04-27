from screen_recorder.ui.tool_palette import ToolPalette


def test_default_tool_is_select(qtbot):
    p = ToolPalette()
    qtbot.addWidget(p)
    assert p.current_tool() == "select"


def test_clicking_tool_emits_signal(qtbot):
    p = ToolPalette()
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.tool_changed, timeout=200) as blocker:
        p.set_current_tool("rect")
    assert blocker.args == ["rect"]


def test_signal_not_reemitted_on_same_tool(qtbot):
    p = ToolPalette()
    qtbot.addWidget(p)
    p.set_current_tool("rect")
    with qtbot.assertNotEmitted(p.tool_changed, wait=200):
        p.set_current_tool("rect")
