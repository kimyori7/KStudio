"""media_probe.probe_duration_ms — ffprobe 동기 길이 조회."""
import json
from unittest.mock import patch, MagicMock

from screen_recorder.services.media_probe import probe_duration_ms


def test_probe_returns_zero_for_empty_path():
    assert probe_duration_ms("") == 0


def test_probe_returns_zero_for_missing_file(tmp_path):
    assert probe_duration_ms(str(tmp_path / "nope.mp4")) == 0


def test_probe_parses_ffprobe_duration(tmp_path):
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"x")
    fake_json = json.dumps({"format": {"duration": "12.345"}}).encode("utf-8")
    with patch("screen_recorder.services.media_probe.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout=fake_json, stderr=b"")
        assert probe_duration_ms(str(fake)) == 12345


def test_probe_returns_zero_on_ffprobe_error(tmp_path):
    fake = tmp_path / "v.mp4"
    fake.write_bytes(b"x")
    with patch("screen_recorder.services.media_probe.subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"err")
        assert probe_duration_ms(str(fake)) == 0
