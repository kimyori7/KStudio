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
    assert s.hotkey.toggle_record == "Ctrl+Shift+T"
    assert s.screenshot.filename_pattern == "screenshot_{date}_{time}"
    assert s.hotkey.screenshot_region == "Ctrl+Shift+R"


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


def test_load_empty_file_returns_defaults_and_backs_up(tmp_path):
    # 절전모드 중 저장이 끊겨 settings.json 이 0바이트가 된 상황 재현.
    # 백업이 없으면 크래시 없이 기본값으로 시작하고, 깨진 원본은 .corrupt 로 치워둠.
    path = tmp_path / "settings.json"
    path.write_text("", encoding="utf-8")

    s = load(path)
    assert s == AppSettings()
    assert not path.exists()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_load_garbage_file_returns_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")

    s = load(path)
    assert s == AppSettings()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_load_corrupt_file_recovers_from_hourly_backup(tmp_path):
    # settings.json 이 0바이트로 깨졌지만 직전 시각 백업(.bak.*)이 있으면 그걸로 복구.
    path = tmp_path / "settings.json"
    good = AppSettings()
    good.video.fps = 60
    save(good, path)
    # 직전 시각 백업을 수동 생성 (save 의 hourly 백업과 동일 형식).
    (path.with_suffix(path.suffix + ".bak.20260606_09")).write_text(
        json.dumps({"video": {"fps": 60}}), encoding="utf-8"
    )
    # 이제 메인 파일을 손상시킨다.
    path.write_text("", encoding="utf-8")

    s = load(path)
    assert s.video.fps == 60          # 백업에서 복구됨
    assert (tmp_path / "settings.json.corrupt").exists()


def test_save_is_atomic_no_tmp_leftover(tmp_path):
    path = tmp_path / "settings.json"
    save(AppSettings(), path)
    assert path.exists()
    assert not (tmp_path / "settings.json.tmp").exists()  # 임시파일 잔여 없음
    # 저장된 내용이 유효한 JSON 으로 다시 로드되는지 확인.
    loaded = load(path)
    assert loaded.video.fps == AppSettings().video.fps


def test_annotation_settings_defaults():
    from screen_recorder.core.settings import AnnotationSettings, AppSettings
    s = AnnotationSettings()
    assert s.last_color == "#E53935"
    assert s.last_thickness == 2

    app = AppSettings()
    assert app.annotation.last_color == "#E53935"
    assert app.annotation.last_thickness == 2


def test_annotation_settings_roundtrip(tmp_path):
    from screen_recorder.core.settings import AppSettings, save, load
    app = AppSettings()
    app.annotation.last_color = "#123456"
    app.annotation.last_thickness = 4

    path = tmp_path / "settings.json"
    save(app, path)
    loaded = load(path)

    assert loaded.annotation.last_color == "#123456"
    assert loaded.annotation.last_thickness == 4


def test_player_settings_defaults():
    from screen_recorder.core.settings import AppSettings
    s = AppSettings()
    assert s.player.skip_seconds == 1
    assert s.player.skip_medium_seconds == 5
    assert s.player.skip_large_seconds == 10


def test_editor_shortcuts_defaults():
    from screen_recorder.core.settings import AppSettings
    s = AppSettings()
    assert s.editor_shortcuts.tool_select == "V"
    assert s.editor_shortcuts.tool_crop == "C"
    assert s.editor_shortcuts.op_background_removal == "Ctrl+Shift+B"
    assert s.editor_shortcuts.file_save == "Ctrl+S"
    assert s.editor_shortcuts.file_export_png == "Ctrl+E"
    assert s.editor_shortcuts.view_actual_size == "Ctrl+0"


def test_preferences_document_dock_and_mode_roundtrip(tmp_path):
    s = AppSettings()
    s.preferences.dock_state_document_b64 = "ZG9j"
    s.preferences.last_mode = "document"
    p = tmp_path / "settings.json"
    save(s, p)
    loaded = load(p)
    assert loaded.preferences.dock_state_document_b64 == "ZG9j"
    assert loaded.preferences.last_mode == "document"


def test_old_settings_without_document_dock_falls_back(tmp_path):
    # 구버전 settings.json (dock_state_document_b64 키 없음) → 기본값 "" 폴백
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"preferences": {"last_mode": "image"}}), encoding="utf-8")
    loaded = load(p)
    assert loaded.preferences.dock_state_document_b64 == ""


def test_last_mode_whitelist_includes_document():
    # app/main.py 의 화이트리스트가 document 를 허용해야 함 (재시작 테마 폴백 방지)
    import inspect
    from screen_recorder.app import main as M
    src = inspect.getsource(M.main)
    assert '"document"' in src and 'last_mode' in src
