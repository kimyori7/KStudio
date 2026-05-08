from screen_recorder.ui.video.player_controls import PlayerControls


def test_emits_play_toggled_on_button(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.play_toggled, timeout=200):
        c.play_btn.click()


def test_emits_speed_changed(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.speed_changed, timeout=200) as blocker:
        c.speed_combo.setCurrentText("2.0×")
    assert blocker.args == [2.0]


def test_set_position_updates_time_label(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_duration_ms(75_000)  # 1:15
    c.set_position_ms(45_000)   # 0:45
    assert "00:45" in c.time_label.text()


def test_volume_signals(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.volume_changed, timeout=200) as blocker:
        c.volume_slider.setValue(50)  # 0..100
    assert abs(blocker.args[0] - 0.5) < 0.01


def test_frame_step_buttons_emit(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.frame_step, timeout=200) as blocker:
        c.frame_back_btn.click()
    assert blocker.args == [-1]
    with qtbot.waitSignal(c.frame_step, timeout=200) as blocker:
        c.frame_forward_btn.click()
    assert blocker.args == [+1]


def test_snapshot_button_signal(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.snapshot_request, timeout=200):
        c.snapshot_btn.click()


def test_audio_disabled_for_gif(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_audio_enabled(False)
    assert not c.volume_slider.isEnabled()
    assert not c.mute_btn.isEnabled()


def test_set_playing_swaps_icon(qtbot):
    """버튼 아이콘이 SVG 로 마이그레이션됨 — text 대신 icon cacheKey 비교."""
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_playing(True)
    pause_key = c.play_btn.icon().cacheKey()
    c.set_playing(False)
    play_key = c.play_btn.icon().cacheKey()
    assert pause_key != play_key


def test_set_muted_swaps_icon(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_muted(True)
    muted_key = c.mute_btn.icon().cacheKey()
    c.set_muted(False)
    unmuted_key = c.mute_btn.icon().cacheKey()
    assert muted_key != unmuted_key


def test_set_speed_updates_combo(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_speed(0.5)
    assert c.speed_combo.currentText() == "0.5×"


def test_mute_button_emits_signal(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.mute_toggled, timeout=200):
        c.mute_btn.click()


def test_fullscreen_button_emits_signal(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    with qtbot.waitSignal(c.fullscreen_toggled, timeout=200):
        c.fullscreen_btn.click()
