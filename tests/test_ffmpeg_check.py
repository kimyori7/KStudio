from pathlib import Path
from unittest.mock import patch

from screen_recorder.core import ffmpeg_check


def test_find_uses_path_when_present():
    with patch("shutil.which", return_value="C:/tools/ffmpeg.exe"):
        result = ffmpeg_check.find_ffmpeg()
        assert result == Path("C:/tools/ffmpeg.exe")


def test_find_returns_none_when_missing():
    with patch("shutil.which", return_value=None):
        with patch.object(ffmpeg_check, "_BUNDLED_PATHS", []):
            assert ffmpeg_check.find_ffmpeg(use_cache=False) is None


def test_find_falls_back_to_bundled(tmp_path):
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"")
    with patch("shutil.which", return_value=None):
        with patch.object(ffmpeg_check, "_BUNDLED_PATHS", [bundled]):
            assert ffmpeg_check.find_ffmpeg(use_cache=False) == bundled
