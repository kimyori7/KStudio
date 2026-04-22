from datetime import datetime
from pathlib import Path
import pytest

from screen_recorder.core.filename import build_filename, resolve_collision


def test_build_filename_default_pattern():
    when = datetime(2026, 4, 22, 14, 30, 52)
    name = build_filename(
        pattern="rec_{date}_{time}",
        when=when,
        mode="video",
        target="fullscreen",
        extension="mp4",
    )
    assert name == "rec_20260422_143052.mp4"


def test_build_filename_with_mode_and_target_tokens():
    when = datetime(2026, 4, 22, 14, 30, 52)
    name = build_filename(
        pattern="cap_{mode}_{target}_{date}",
        when=when,
        mode="gif",
        target="region",
        extension="gif",
    )
    assert name == "cap_gif_region_20260422.gif"


def test_resolve_collision_returns_same_path_when_no_conflict(tmp_path):
    target = tmp_path / "rec.mp4"
    assert resolve_collision(target) == target


def test_resolve_collision_appends_underscore_n_when_conflict(tmp_path):
    (tmp_path / "rec.mp4").write_bytes(b"")
    assert resolve_collision(tmp_path / "rec.mp4") == tmp_path / "rec_2.mp4"

    (tmp_path / "rec_2.mp4").write_bytes(b"")
    assert resolve_collision(tmp_path / "rec.mp4") == tmp_path / "rec_3.mp4"


def test_build_filename_rejects_unknown_token():
    with pytest.raises(ValueError, match="unknown token"):
        build_filename(
            pattern="rec_{nope}",
            when=datetime.now(),
            mode="video",
            target="fullscreen",
            extension="mp4",
        )
