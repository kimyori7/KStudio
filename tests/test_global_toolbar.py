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


def test_keep_visible_toggle_emits_signal(qtbot):
    """'내 화면에 보이기' 체크박스 토글 → keep_visible_during_capture_changed."""
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert tb.keep_visible_chk.isChecked() is False
    with qtbot.waitSignal(tb.keep_visible_during_capture_changed, timeout=200) as blocker:
        tb.keep_visible_chk.setChecked(True)
    assert blocker.args == [True]


def test_keep_visible_toggle_off_emits_false(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.keep_visible_chk.setChecked(True)
    with qtbot.waitSignal(tb.keep_visible_during_capture_changed, timeout=200) as blocker:
        tb.keep_visible_chk.setChecked(False)
    assert blocker.args == [False]


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


def test_document_mode_button_emits(qtbot):
    from screen_recorder.ui.mode_controller import AppMode
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    received = []
    tb.mode_clicked.connect(received.append)
    tb.document_btn.click()
    assert received == [AppMode.DOCUMENT]


def test_document_mode_hides_recording_and_capture(qtbot):
    from screen_recorder.ui.mode_controller import AppMode
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.show()
    tb.set_mode(AppMode.DOCUMENT)
    assert not tb.record_btn.isVisible()
    assert not tb.capture_region_btn.isVisible()


def test_doc_refresh_and_auto_reload_only_in_document_mode(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    tb.show()
    for mode in (AppMode.IMAGE, AppMode.VIDEO):
        tb.set_mode(mode)
        assert not tb.doc_refresh_btn.isVisible()
        assert not tb.doc_auto_reload_chk.isVisible()
    tb.set_mode(AppMode.DOCUMENT)
    assert tb.doc_refresh_btn.isVisible()
    assert tb.doc_auto_reload_chk.isVisible()
    # «내 화면에 보이기» 바로 오른쪽 순서
    lay = tb.layout()
    idx = [lay.itemAt(i).widget() for i in range(lay.count())]
    k = idx.index(tb.keep_visible_chk)
    assert idx[k + 1] is tb.doc_refresh_btn
    assert idx[k + 2] is tb.doc_auto_reload_chk


def test_doc_refresh_click_emits(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.doc_refresh_clicked, timeout=200):
        tb.doc_refresh_btn.click()


def test_doc_auto_reload_emits_on_user_click_not_on_code_sync(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    seen = []
    tb.doc_auto_reload_changed.connect(seen.append)
    tb.set_doc_auto_reload(False)           # 코드 동기화 — 신호 없음
    assert seen == [] and not tb.doc_auto_reload_chk.isChecked()
    tb.doc_auto_reload_chk.click()          # 사용자
    assert seen == [True]


def test_doc_refresh_pending_marker_and_enabled(qtbot):
    tb = GlobalToolbar()
    qtbot.addWidget(tb)
    assert "●" not in tb.doc_refresh_btn.text()
    tb.set_doc_refresh_pending(True)
    assert "●" in tb.doc_refresh_btn.text()
    assert "바뀐 내용" in tb.doc_refresh_btn.toolTip()
    tb.set_doc_refresh_pending(False)
    assert "●" not in tb.doc_refresh_btn.text()
    tb.set_doc_refresh_enabled(False)
    assert not tb.doc_refresh_btn.isEnabled()
