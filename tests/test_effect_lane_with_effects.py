"""EffectLane 의 effects 보관 API."""
import pytest

from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.effect_lane import EffectLane


def test_lane_starts_with_no_effects(qtbot):
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    assert lane.effects() == []


def test_set_effects_stores_and_redraws(qtbot):
    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    lane.set_duration_ms(10_000)
    es = [
        CaptionEffect(in_ms=0, out_ms=1000, text="a"),
        CaptionEffect(in_ms=2000, out_ms=4000, text="b"),
    ]
    lane.set_effects(es)
    assert lane.effects() == es


def test_set_effects_filters_to_lane_type(qtbot):
    """다른 type 의 효과를 줘도 자기 type 의 것만 보관."""
    from screen_recorder.effects.types.speed import SpeedEffect

    lane = EffectLane(effect_type="caption", header_label="캡션", color="#3b82f6")
    qtbot.addWidget(lane)
    es = [
        CaptionEffect(in_ms=0, out_ms=1000, text="a"),
        SpeedEffect(in_ms=2000, out_ms=3000, rate=2.0),
    ]
    lane.set_effects(es)
    assert len(lane.effects()) == 1
    assert lane.effects()[0].type == "caption"
