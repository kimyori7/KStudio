from screen_recorder.core.state import RecorderState
from screen_recorder.ui.global_toolbar import GlobalToolbar
from screen_recorder.ui.mode_controller import AppMode


def test_default_buttons_in_idle(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    # 영상 모드 + IDLE: record 만 표시
    tb.set_mode(AppMode.VIDEO)
    assert not tb.record_btn.isHidden()
    assert tb.pause_btn.isHidden()
    assert tb.stop_btn.isHidden()


def test_image_mode_hides_recording_controls(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.IMAGE)
    # 이미지 모드: 녹화 컨트롤 숨김, 캡처 + 저장/복사 표시
    assert tb.record_btn.isHidden()
    assert tb.pause_btn.isHidden()
    assert tb.stop_btn.isHidden()
    assert not tb.capture_region_btn.isHidden()
    assert not tb.capture_full_btn.isHidden()
    assert not tb.save_btn.isHidden()
    assert not tb.copy_btn.isHidden()


def test_video_mode_hides_capture_and_actions(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    # 영상 모드: 캡처/저장/복사 숨김
    assert tb.capture_region_btn.isHidden()
    assert tb.capture_full_btn.isHidden()
    assert tb.save_btn.isHidden()
    assert tb.copy_btn.isHidden()


def test_mode_toggle_emits(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_clicked, timeout=200) as blocker:
        tb.image_btn.click()
    assert blocker.args == [AppMode.IMAGE]
    with qtbot.waitSignal(tb.mode_clicked, timeout=200) as blocker:
        tb.video_btn.click()
    assert blocker.args == [AppMode.VIDEO]


def test_set_mode_updates_active_button(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    assert tb.video_btn.isChecked()
    assert not tb.image_btn.isChecked()


def test_video_mode_hides_save_copy(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_mode(AppMode.VIDEO)
    assert tb.save_btn.isHidden()
    assert tb.copy_btn.isHidden()


def test_recording_state_changes_button_visibility(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    # 영상 모드에서만 녹화 컨트롤이 의미 있음
    tb.set_mode(AppMode.VIDEO)
    tb.set_recording_state(RecorderState.RECORDING)
    assert not tb.pause_btn.isHidden()
    assert not tb.stop_btn.isHidden()
    assert tb.record_btn.isHidden()


def test_target_changed_signal(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.target_changed, timeout=200) as blocker:
        tb._target_btns["region"].click()
    assert blocker.args[0] == "region"


def test_format_changed_signal(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_value_changed, timeout=200) as blocker:
        tb._format_btns["gif"].click()
    assert blocker.args[0] == "gif"


def test_set_target_updates_button_state(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.set_target("window")
    assert tb._target_btns["window"].isChecked()
    assert tb.current_target() == "window"


def test_global_toolbar_has_remove_bg_action_no_button(qtbot):
    """배경 제거 버튼은 ToolPalette 로 옮겨졌고 GlobalToolbar 에는 QAction 만 남아있다."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert tb.find_action("remove_bg") is not None
    assert not hasattr(tb, "remove_bg_btn")
