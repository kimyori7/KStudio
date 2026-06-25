"""SpeedEffect dataclass."""
import pytest
from screen_recorder.effects.types.speed import SpeedEffect


def test_speed_minimal_construct():
    s = SpeedEffect(in_ms=0, out_ms=5000, rate=2.0)
    assert s.type == "speed"
    assert s.rate == 2.0
    assert s.audio == "auto"      # 기본
    assert s.show_hud is False    # 2026-06-23 기본 OFF 로 변경


def test_speed_explicit_construct():
    s = SpeedEffect(
        in_ms=0, out_ms=5000, rate=5.0,
        audio="mute", show_hud=False,
    )
    assert s.audio == "mute"
    assert s.show_hud is False


def test_speed_rejects_invalid_rate():
    with pytest.raises(ValueError, match="rate"):
        SpeedEffect(in_ms=0, out_ms=1000, rate=0.0)
    with pytest.raises(ValueError, match="rate"):
        SpeedEffect(in_ms=0, out_ms=1000, rate=-1.0)
    with pytest.raises(ValueError, match="rate"):
        SpeedEffect(in_ms=0, out_ms=1000, rate=33.0)  # > 32 상한


def test_speed_rejects_invalid_audio_mode():
    with pytest.raises(ValueError, match="audio"):
        SpeedEffect(in_ms=0, out_ms=1000, rate=2.0, audio="bogus")
