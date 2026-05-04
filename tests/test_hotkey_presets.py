"""단축키 프리셋 단위 테스트."""
from __future__ import annotations

from screen_recorder.core.settings import AppSettings
from screen_recorder.core.hotkey_presets import (
    PRESETS, apply_preset, detect_preset, is_first_run,
)


def test_presets_have_two_options():
    assert "windows-standard" in PRESETS
    assert "goom-pot" in PRESETS


def test_apply_windows_preset_overrides_hotkeys():
    s = AppSettings()
    apply_preset(s, "windows-standard")
    assert s.hotkey.toggle_record == "Ctrl+Alt+R"
    assert s.hotkey.screenshot_region == "Ctrl+Win+S"
    assert s.hotkey.preset_name == "windows-standard"


def test_apply_goompot_preset():
    s = AppSettings()
    apply_preset(s, "goom-pot")
    assert s.hotkey.toggle_record == "Ctrl+Shift+T"
    assert s.hotkey.screenshot_region == "Ctrl+Shift+R"
    assert s.hotkey.preset_name == "goom-pot"


def test_apply_unknown_preset_noop():
    s = AppSettings()
    s.hotkey.toggle_record = "X"
    apply_preset(s, "nonexistent")
    assert s.hotkey.toggle_record == "X"   # 변경 없음


def test_apply_preset_overrides_editor_shortcuts():
    s = AppSettings()
    s.editor_shortcuts.tool_crop = "X"   # 사용자가 임의 변경
    apply_preset(s, "goom-pot")
    assert s.editor_shortcuts.tool_crop == "C"   # 프리셋 값으로 복귀


def test_detect_preset_goompot_default():
    """초기 default = goom-pot 과 일치."""
    s = AppSettings()
    assert detect_preset(s) == "goom-pot"


def test_detect_preset_custom_when_modified():
    s = AppSettings()
    apply_preset(s, "windows-standard")
    s.hotkey.toggle_record = "Ctrl+Q"   # 한 키 수정
    assert detect_preset(s) == "custom"


def test_is_first_run_when_preset_name_empty():
    s = AppSettings()
    s.hotkey.preset_name = ""
    assert is_first_run(s) is True


def test_is_first_run_false_after_apply():
    s = AppSettings()
    apply_preset(s, "goom-pot")
    assert is_first_run(s) is False


def test_apply_preset_doesnt_touch_other_settings():
    s = AppSettings()
    s.general.output_dir = "C:/myvideos"
    s.video.fps = 60
    apply_preset(s, "windows-standard")
    assert s.general.output_dir == "C:/myvideos"
    assert s.video.fps == 60
