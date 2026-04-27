from PySide6.QtGui import QColor

from screen_recorder.ui.annotation_toolbar import AnnotationToolbar


# 도구 그룹 테스트 (tool_ids/current_tool_id/set_current_tool/tool_changed) 는
# Task 18 에서 도구 그룹과 함께 제거됨. 동등한 검증은 tests/test_tool_palette.py 에 있음.


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
