import json
from pathlib import Path

from screen_recorder.core.settings import (
    AppSettings, VideoSettings, GifSettings, SoundSettings,
    HotkeySettings, GeneralSettings, load, save,
)


def test_default_settings_have_expected_values():
    s = AppSettings()
    assert s.general.mode == "video"
    assert s.general.filename_pattern == "rec_{date}_{time}"
    assert s.video.container == "mp4"
    assert s.video.codec == "h264"
    assert s.video.fps == 30
    assert s.video.scale_percent == 100
    assert s.video.bitrate_kbps == 8000
    assert s.gif.fps == 10
    assert s.gif.scale_percent == 100
    assert s.gif.colors == 256
    assert s.sound.system_audio_enabled is True
    assert s.sound.codec == "aac"
    assert s.sound.bitrate_kbps == 192
    assert s.hotkey.toggle_record == "F9"


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = AppSettings()
    s.video.fps = 60
    s.gif.scale_percent = 47
    s.hotkey.toggle_record = "Ctrl+Shift+R"
    save(s, path)

    loaded = load(path)
    assert loaded.video.fps == 60
    assert loaded.gif.scale_percent == 47
    assert loaded.hotkey.toggle_record == "Ctrl+Shift+R"


def test_load_missing_file_returns_defaults(tmp_path):
    s = load(tmp_path / "does_not_exist.json")
    assert s == AppSettings()


def test_load_partial_file_fills_defaults(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"video": {"fps": 60}}), encoding="utf-8")

    s = load(path)
    assert s.video.fps == 60
    assert s.video.codec == "h264"  # default
    assert s.gif.fps == 10  # default
