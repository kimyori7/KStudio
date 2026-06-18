from pathlib import Path

from screen_recorder.core import settings as s


def test_youtube_settings_defaults():
    app = s.AppSettings()
    assert app.youtube.video_dir == ""
    assert app.youtube.mp3_dir == ""
    assert app.youtube.video_quality == "best"
    assert app.youtube.mp3_bitrate == "192"


def test_default_download_dir():
    assert s.default_download_dir() == Path.home() / "Downloads"


def test_youtube_settings_roundtrip(tmp_path):
    app = s.AppSettings()
    app.youtube.video_dir = r"C:\vids"
    app.youtube.mp3_bitrate = "320"
    p = tmp_path / "settings.json"
    s.save(app, p)
    loaded = s.load(p)
    assert loaded.youtube.video_dir == r"C:\vids"
    assert loaded.youtube.mp3_bitrate == "320"


def test_missing_youtube_key_uses_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"general": {"fps": 30}}', encoding="utf-8")
    loaded = s.load(p)
    assert loaded.youtube.video_dir == ""   # 누락 키 → 기본값
    assert loaded.youtube.video_quality == "best"
