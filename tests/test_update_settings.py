from pathlib import Path
from screen_recorder.core import settings as S


def test_update_settings_defaults():
    s = S.AppSettings()
    assert s.update.auto_check is True
    assert s.update.skip_version == ""
    assert s.update.last_check_iso == ""


def test_update_settings_roundtrip(tmp_path: Path):
    s = S.AppSettings()
    s.update.auto_check = False
    s.update.skip_version = "0.1.9"
    p = tmp_path / "settings.json"
    S.save(s, p)
    loaded = S.load(p)
    assert loaded.update.auto_check is False
    assert loaded.update.skip_version == "0.1.9"


def test_missing_update_block_uses_defaults(tmp_path: Path):
    # 구버전 settings.json(=update 블록 없음) 로드 시 기본값으로 채워져야 함.
    p = tmp_path / "settings.json"
    p.write_text('{"preferences": {"language": "ko"}}', encoding="utf-8")
    loaded = S.load(p)
    assert loaded.update.auto_check is True
