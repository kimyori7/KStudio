from screen_recorder.core.settings import UpdateSettings, AppSettings, _from_dict


def test_default_is_empty():
    assert UpdateSettings().last_seen_version == ""


def test_old_settings_without_field_defaults_empty():
    # 구버전 settings.json (필드 없음) 로드 시 기본값 "".
    raw = {"update": {"auto_check": True, "skip_version": "", "last_check_iso": ""}}
    s = _from_dict(AppSettings, raw)
    assert s.update.last_seen_version == ""


def test_roundtrip_preserves_value():
    raw = {"update": {"last_seen_version": "1.0.0"}}
    s = _from_dict(AppSettings, raw)
    assert s.update.last_seen_version == "1.0.0"
