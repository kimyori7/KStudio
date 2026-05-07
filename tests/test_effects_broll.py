"""BrollEffect dataclass."""
import pytest
from screen_recorder.effects.types.broll import BrollEffect, PipConfig


def test_broll_fullscreen_minimal():
    b = BrollEffect(
        in_ms=0, out_ms=5000,
        src="broll/intro.mp4",
        placement="fullscreen",
    )
    assert b.type == "broll"
    assert b.placement == "fullscreen"
    assert b.audio_mix == "both"
    assert b.audio_balance == 0.5    # 50/50
    assert b.pip is None             # fullscreen 일 땐 pip 없음


def test_broll_pip_with_config():
    b = BrollEffect(
        in_ms=0, out_ms=5000,
        src="broll/clip.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    assert b.pip.corner == "bottom-right"
    assert b.pip.size_ratio == 0.3


def test_broll_rejects_invalid_placement():
    with pytest.raises(ValueError, match="placement"):
        BrollEffect(in_ms=0, out_ms=1000, src="x", placement="background")


def test_broll_rejects_invalid_audio_mix():
    with pytest.raises(ValueError, match="audio_mix"):
        BrollEffect(in_ms=0, out_ms=1000, src="x", placement="fullscreen", audio_mix="loud")


def test_broll_rejects_invalid_audio_balance():
    with pytest.raises(ValueError, match="audio_balance"):
        BrollEffect(in_ms=0, out_ms=1000, src="x", placement="fullscreen", audio_balance=1.1)


def test_pip_rejects_invalid_corner():
    with pytest.raises(ValueError, match="corner"):
        PipConfig(corner="middle", size_ratio=0.3)


def test_pip_rejects_invalid_size_ratio():
    with pytest.raises(ValueError, match="size_ratio"):
        PipConfig(corner="bottom-right", size_ratio=0.05)  # < 0.1
    with pytest.raises(ValueError, match="size_ratio"):
        PipConfig(corner="bottom-right", size_ratio=0.6)   # > 0.5
