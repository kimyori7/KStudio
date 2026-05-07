"""편집 모드 토글 버튼."""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.ui.video.edit_mode_toggle import EditModeToggle


def test_default_off(qtbot):
    btn = EditModeToggle()
    qtbot.addWidget(btn)
    assert btn.is_on() is False
    assert btn.isCheckable() is True


def test_click_toggles_state(qtbot):
    btn = EditModeToggle()
    qtbot.addWidget(btn)
    with qtbot.waitSignal(btn.toggled_changed, timeout=1000) as blocker:
        btn.click()
    assert blocker.args == [True]
    assert btn.is_on() is True
    with qtbot.waitSignal(btn.toggled_changed, timeout=1000) as blocker:
        btn.click()
    assert blocker.args == [False]
    assert btn.is_on() is False


def test_set_on_programmatically_emits_signal(qtbot):
    btn = EditModeToggle()
    qtbot.addWidget(btn)
    with qtbot.waitSignal(btn.toggled_changed, timeout=1000) as blocker:
        btn.set_on(True)
    assert blocker.args == [True]


def test_set_on_idempotent_no_duplicate_signal(qtbot):
    """set_on(True) 를 두 번 호출해도 시그널은 한 번만."""
    btn = EditModeToggle()
    qtbot.addWidget(btn)
    btn.set_on(True)
    received: list[bool] = []
    btn.toggled_changed.connect(received.append)
    btn.set_on(True)   # 이미 True
    assert received == []


def test_tooltip_present(qtbot):
    btn = EditModeToggle()
    qtbot.addWidget(btn)
    assert btn.toolTip()  # 비어있지 않음
