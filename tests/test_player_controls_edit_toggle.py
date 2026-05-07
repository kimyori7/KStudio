"""PlayerControls 의 편집 모드 토글 버튼."""
import pytest

from screen_recorder.ui.video.player_controls import PlayerControls


def test_player_controls_has_edit_toggle(qtbot):
    pc = PlayerControls()
    qtbot.addWidget(pc)
    # 편집 토글 위젯 존재
    assert hasattr(pc, "edit_toggle")
    assert pc.edit_toggle.is_on() is False


def test_edit_toggle_click_emits_request(qtbot):
    pc = PlayerControls()
    qtbot.addWidget(pc)
    with qtbot.waitSignal(pc.edit_mode_change_requested, timeout=1000) as blocker:
        pc.edit_toggle.click()
    assert blocker.args == [True]


def test_set_edit_mode_external_updates_button(qtbot):
    """외부에서 set_edit_mode_button(True) 호출 시 버튼 상태 동기화."""
    pc = PlayerControls()
    qtbot.addWidget(pc)
    pc.set_edit_mode_button(True)
    assert pc.edit_toggle.is_on() is True
    pc.set_edit_mode_button(False)
    assert pc.edit_toggle.is_on() is False
