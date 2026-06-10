"""새 효과의 비례 기본 길이 — `default_effect_duration_ms` 순수 함수.

영상이 길수록 새 캡션/효과 블록을 길게 만들어 타임라인에서 잡기 쉽게 하되,
짧은 영상은 기존 고정 최소값을 유지하고 cut 류는 비례 적용에서 제외한다.
"""
from screen_recorder.ui.video_tab import (
    default_effect_duration_ms,
    _PROPORTIONAL_RATIO,
    _PROPORTIONAL_CAP_MS,
)

# `_add_effect_at` 가 넘기는 것과 동일한 효과별 고정 최소값.
_FIXED = {
    "caption": 3000, "speed": 5000, "zoom": 2000,
    "broll": 5000, "cut": 1000, "arrow": 2000,
}


def test_short_video_keeps_fixed_floor():
    # 10초 영상: 5% = 500ms < 3000 floor → 기존 동작 그대로.
    assert default_effect_duration_ms("caption", 10_000, _FIXED) == 3000


def test_mid_video_scales_proportionally():
    # 5분(300s) 영상: 5% = 15초.
    assert default_effect_duration_ms("caption", 300_000, _FIXED) == 15_000


def test_long_video_clamped_to_cap():
    # 30분(1800s): 5% = 90초 = 상한.
    assert default_effect_duration_ms("caption", 1_800_000, _FIXED) == 90_000
    # 1시간(3600s): 5% = 180초 → 상한 90초로 클램프.
    assert default_effect_duration_ms("caption", 3_600_000, _FIXED) == 90_000


def test_speed_floor_respected_on_short_video():
    # speed 의 고정 최소값은 5초 — 짧은 영상에서 살아있어야 함.
    assert default_effect_duration_ms("speed", 10_000, _FIXED) == 5000


def test_all_proportional_types_scale():
    # caption/speed/zoom/broll/arrow 모두 30분 영상에서 상한까지 커짐.
    for t in ("caption", "speed", "zoom", "broll", "arrow"):
        assert default_effect_duration_ms(t, 1_800_000, _FIXED) == _PROPORTIONAL_CAP_MS


def test_cut_types_never_scale():
    # cut 류(마커·구간 삭제)는 영상 길이와 무관하게 고정값 유지.
    assert default_effect_duration_ms("cut", 1_800_000, _FIXED) == 1000
    assert default_effect_duration_ms("cut_splice", 1_800_000, _FIXED) == 3000  # 미등록 → 3000
    assert default_effect_duration_ms("cut_range", 1_800_000, _FIXED) == 3000


def test_zero_or_negative_total_returns_floor():
    assert default_effect_duration_ms("caption", 0, _FIXED) == 3000
    assert default_effect_duration_ms("caption", -5000, _FIXED) == 3000


def test_ratio_and_cap_constants_are_sane():
    # 회귀 방지 — 설계값(5%, 90초) 고정.
    assert _PROPORTIONAL_RATIO == 0.05
    assert _PROPORTIONAL_CAP_MS == 90_000
