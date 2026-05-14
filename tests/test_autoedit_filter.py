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


def test_caption_segments_to_caption_effects_sentence_split():
    raw = AutoEditResult(
        source_hash="x",
        transcript_segments=[
            {"in_ms": 0, "out_ms": 1500, "text": "안녕하세요."},
            {"in_ms": 1500, "out_ms": 3000, "text": "자동 편집 테스트입니다."},
        ],
    )
    s = default_settings()
    s.silence_enabled = False; s.scene_enabled = False
    s.caption_max_chars = 100   # 충분히 큼 → 분할 없음
    effects = apply_thresholds(raw, s)
    assert len(effects) == 2
    assert all(e.type == "caption" for e in effects)
    assert effects[0].text == "안녕하세요."


def test_caption_max_chars_splits_long_segment():
    raw = AutoEditResult(
        source_hash="x",
        transcript_segments=[
            {"in_ms": 0, "out_ms": 6000, "text": "0123456789" * 4},  # 40자
        ],
    )
    s = default_settings()
    s.silence_enabled = False; s.scene_enabled = False
    s.caption_max_chars = 10
    effects = apply_thresholds(raw, s)
    # 40 / 10 = 4 분할.
    assert len(effects) == 4
    assert effects[0].in_ms == 0
    assert effects[-1].out_ms == 6000
