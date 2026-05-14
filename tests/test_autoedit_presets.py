from screen_recorder.autoedit.presets import AutoEditSettings, default_settings


def test_default_settings_all_enabled_except_bpm():
    s = default_settings()
    assert s.silence_enabled is True
    assert s.caption_enabled is True
    assert s.scene_enabled is True
    assert s.bpm_enabled is False


def test_default_thresholds():
    s = default_settings()
    assert s.silence_min_ms == 800
    assert s.caption_max_chars == 30
    assert s.caption_split == "sentence"
    assert s.scene_sensitivity == 30
    assert s.scene_zoom_strength == 1.3
    assert s.bpm_confidence == 0.6
