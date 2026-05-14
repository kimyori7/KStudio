"""filter.apply_thresholds — raw 재분석 없이 메모리만 필터링."""
from screen_recorder.autoedit.result import AutoEditResult
from screen_recorder.autoedit.presets import default_settings
from screen_recorder.autoedit.filter import apply_thresholds


def test_disabled_settings_produce_no_effects():
    raw = AutoEditResult(
        source_hash="x",
        silence_segments=[(100, 1000)],
        transcript_segments=[{"in_ms": 0, "out_ms": 2000, "text": "hi"}],
        scene_changes=[(500, 50.0)],
    )
    s = default_settings()
    s.silence_enabled = False
    s.caption_enabled = False
    s.scene_enabled = False
    effects = apply_thresholds(raw, s)
    assert effects == []


def test_silence_threshold_filters_short_gaps():
    raw = AutoEditResult(source_hash="x", silence_segments=[
        (0, 500),
        (1000, 2000),
    ])
    s = default_settings()
    s.caption_enabled = False
    s.scene_enabled = False
    s.silence_min_ms = 800
    effects = apply_thresholds(raw, s)
    assert len(effects) == 1
