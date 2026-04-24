import json

from screen_recorder.core.settings import (
    AppSettings, ScreenshotSettings, HotkeySettings, load, save,
)


def test_screenshot_settings_defaults():
    s = ScreenshotSettings()
    assert s.save_dir == ""
    assert s.filename_pattern == "screenshot_{date}_{time}"
    assert s.format == "png"
    assert s.magnifier_enabled is True
    assert s.viewer_x == -1 and s.viewer_y == -1
    assert s.viewer_w == -1 and s.viewer_h == -1


def test_hotkey_defaults_include_screenshot_fields():
    h = HotkeySettings()
    assert h.toggle_record == "Ctrl+Shift+T"
    assert h.screenshot_region == "Ctrl+Shift+R"
    assert h.screenshot_full == ""


def test_app_settings_has_screenshot_section():
    s = AppSettings()
    assert isinstance(s.screenshot, ScreenshotSettings)


def test_roundtrip_preserves_screenshot_section(tmp_path):
    path = tmp_path / "s.json"
    s = AppSettings()
    s.screenshot.save_dir = "D:/caps"
    s.screenshot.magnifier_enabled = False
    s.hotkey.screenshot_region = "F10"
    save(s, path)

    loaded = load(path)
    assert loaded.screenshot.save_dir == "D:/caps"
    assert loaded.screenshot.magnifier_enabled is False
    assert loaded.hotkey.screenshot_region == "F10"


def test_load_legacy_file_without_screenshot_section_fills_defaults(tmp_path):
    """기존 사용자 파일(스크린샷 섹션 없음)을 로드해도 깨지지 않아야 한다."""
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "general": {"mode": "video"},
        "hotkey": {"toggle_record": "F9"},  # 구버전 값은 유지
    }), encoding="utf-8")

    s = load(path)
    assert s.hotkey.toggle_record == "F9"  # 기존 값 보존
    assert s.screenshot.filename_pattern == "screenshot_{date}_{time}"  # 기본값
    assert s.hotkey.screenshot_region == "Ctrl+Shift+R"  # 누락된 새 필드는 기본값
