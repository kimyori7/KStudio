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


def test_caption_max_chars_wraps_within_single_effect():
    """한 자막 안에서 줄바꿈 — 시간 분할 X. (2026-05-15 fix)"""
    raw = AutoEditResult(
        source_hash="x",
        transcript_segments=[
            {"in_ms": 0, "out_ms": 6000, "text": "0123456789" * 4},  # 공백 없는 40자
        ],
    )
    s = default_settings()
    s.silence_enabled = False; s.scene_enabled = False
    s.caption_max_chars = 10
    effects = apply_thresholds(raw, s)
    # 1개 effect, text 안에 \n 으로 4줄.
    assert len(effects) == 1
    assert effects[0].in_ms == 0
    assert effects[0].out_ms == 6000
    lines = effects[0].text.split("\n")
    assert len(lines) == 4
    assert all(len(l) <= 10 for l in lines)


def test_caption_wrap_prefers_word_boundary():
    """공백 있는 텍스트는 단어 단위로 wrap (영문/한글 띄어쓰기 보존)."""
    raw = AutoEditResult(
        source_hash="x",
        transcript_segments=[
            {"in_ms": 0, "out_ms": 5000, "text": "안녕 자동 편집 테스트 입니다"},
        ],
    )
    s = default_settings()
    s.silence_enabled = False; s.scene_enabled = False
    s.caption_max_chars = 10
    effects = apply_thresholds(raw, s)
    assert len(effects) == 1
    lines = effects[0].text.split("\n")
    # 단어 경계 보존 — 단어 중간에 잘리지 않음.
    for line in lines:
        assert "  " not in line   # 줄 안 이중 공백 X
        assert not line.startswith(" ") and not line.endswith(" ")


def test_scene_changes_to_zoom_effects():
    raw = AutoEditResult(source_hash="x", scene_changes=[(5000, 35.0), (10000, 28.0)])
    s = default_settings()
    s.silence_enabled = False; s.caption_enabled = False
    s.scene_enabled = True
    s.scene_sensitivity = 30
    effects = apply_thresholds(raw, s)
    # 30 임계값 이상만 — 35.0 통과, 28.0 제외.
    zooms = [e for e in effects if e.type == "zoom"]
    assert len(zooms) == 1
    assert zooms[0].in_ms == 5000
    assert zooms[0].out_ms == 7000   # 2초 지속
    assert zooms[0].mode == "magnify_region"


def test_bpm_snaps_caption_in_ms_to_nearest_beat():
    raw = AutoEditResult(
        source_hash="x",
        transcript_segments=[{"in_ms": 1100, "out_ms": 2000, "text": "hi"}],
        beats=[(1000, 0.8), (1500, 0.8)],
    )
    s = default_settings()
    s.silence_enabled = False; s.scene_enabled = False
    s.bpm_enabled = True
    s.bpm_confidence = 0.6
    effects = apply_thresholds(raw, s)
    caps = [e for e in effects if e.type == "caption"]
    # 1100ms 가까운 비트 = 1000ms (Δ=100) vs 1500ms (Δ=400) → 1000 으로 snap.
    assert caps[0].in_ms == 1000
