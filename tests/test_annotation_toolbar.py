from PySide6.QtGui import QColor

from screen_recorder.ui.annotation_toolbar import AnnotationToolbar


def test_toolbar_has_four_tools(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    assert set(tb.tool_ids()) == {"select", "rect", "arrow", "text"}


def test_toolbar_default_tool_is_select(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    assert tb.current_tool_id() == "select"


def test_toolbar_tool_change_emits_signal(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.tool_changed, timeout=500) as blocker:
        tb.set_current_tool("rect")
    assert blocker.args == ["rect"]


def test_toolbar_has_eight_preset_colors(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    assert len(tb.preset_colors()) == 8


def test_toolbar_default_color_is_red(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    assert tb.current_color() == QColor("#E53935")


def test_toolbar_color_change_signal(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.color_changed, timeout=500):
        tb.set_current_color(QColor("#00FF00"))


def test_toolbar_thickness_default_is_2(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    assert tb.current_thickness_step() == 2


def test_toolbar_thickness_change_signal(qtbot):
    tb = AnnotationToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.thickness_changed, timeout=500) as blocker:
        tb.set_current_thickness_step(4)
    assert blocker.args == [4]
