"""단축키 프리셋 단위 테스트."""
from __future__ import annotations

from screen_recorder.core.settings import AppSettings
from screen_recorder.core.hotkey_presets import (
    PRESETS, apply_preset, detect_preset, is_first_run,
)


def test_presets_have_two_options():
    assert "windows-standard" in PRESETS
    assert "kstudio-default" in PRESETS


def test_apply_windows_preset_overrides_hotkeys():
    s = AppSettings()
    apply_preset(s, "windows-standard")
    assert s.hotkey.toggle_record == "Ctrl+Alt+R"
    assert s.hotkey.screenshot_region == "Ctrl+Meta+S"   # Win 키 = Meta (Qt 표기)
    assert s.hotkey.preset_name == "windows-standard"


def test_windows_preset_keys_parse_through_qkeysequence():
    """프리셋 값이 QKeySequence 로 파싱돼 빈 문자열이 아니어야 — UI 위젯 표시 회귀."""
    from PySide6.QtGui import QKeySequence
    s = AppSettings()
    apply_preset(s, "windows-standard")
    for key in (s.hotkey.toggle_record, s.hotkey.screenshot_region,
                 s.hotkey.screenshot_full):
        if key:   # 빈 문자열은 스킵 (toggle_record_full 등)
            assert QKeySequence(key).toString(), f"파싱 실패: {key!r}"


def test_apply_kstudio_default_preset():
    s = AppSettings()
    apply_preset(s, "kstudio-default")
    assert s.hotkey.toggle_record == "Ctrl+Shift+T"
    assert s.hotkey.screenshot_region == "Ctrl+Shift+R"
    assert s.hotkey.preset_name == "kstudio-default"


def test_apply_unknown_preset_noop():
    s = AppSettings()
    s.hotkey.toggle_record = "X"
    apply_preset(s, "nonexistent")
    assert s.hotkey.toggle_record == "X"   # 변경 없음


def test_apply_preset_overrides_editor_shortcuts():
    s = AppSettings()
    s.editor_shortcuts.tool_crop = "X"   # 사용자가 임의 변경
    apply_preset(s, "kstudio-default")
    assert s.editor_shortcuts.tool_crop == "C"   # 프리셋 값으로 복귀


def test_detect_preset_goompot_default():
    """초기 default = kstudio-default 과 일치."""
    s = AppSettings()
    assert detect_preset(s) == "kstudio-default"


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
    """첫 실행은 글로벌 + 영상 두 차원 모두 결정돼야 false."""
    from screen_recorder.core.hotkey_presets import apply_player_preset
    s = AppSettings()
    apply_preset(s, "kstudio-default")
    apply_player_preset(s, "kstudio-default")
    assert is_first_run(s) is False


def test_apply_player_preset_goom_style():
    from screen_recorder.core.hotkey_presets import apply_player_preset
    s = AppSettings()
    apply_player_preset(s, "goom-style")
    assert s.player_hotkeys.frame_back == "A"
    assert s.player_hotkeys.frame_forward == "D"
    assert s.player_hotkeys.snapshot == "Ctrl+G"
    assert s.player_hotkeys.preset_name == "goom-style"


def test_detect_player_preset_default():
    from screen_recorder.core.hotkey_presets import detect_player_preset
    s = AppSettings()
    # default frame_back/forward/snapshot 가 kstudio-default 와 일치
    assert detect_player_preset(s) == "kstudio-default"


def test_detect_player_preset_custom_after_edit():
    from screen_recorder.core.hotkey_presets import detect_player_preset
    s = AppSettings()
    s.player_hotkeys.frame_back = "Z"
    assert detect_player_preset(s) == "custom"


def test_apply_preset_doesnt_touch_other_settings():
    s = AppSettings()
    s.general.output_dir = "C:/myvideos"
    s.video.fps = 60
    apply_preset(s, "windows-standard")
    assert s.general.output_dir == "C:/myvideos"
    assert s.video.fps == 60
