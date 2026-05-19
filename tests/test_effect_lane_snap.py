"""EffectLane — playhead 스냅 helper.

사용자 의도 "줌, 배속 등 편집하는게 여기 가까이 가면 달라붙는 기능."
새 캡션 / 줌 / 배속 / broll 의 in/out 가 재생 위치 ±_SNAP_PX (8px) 안에
들어오면 정확히 playhead 시간으로 스냅.
"""
from __future__ import annotations

import pytest

from screen_recorder.ui.video.effect_lane import EffectLane


def _make_lane(qtbot, *, duration_ms: int = 10_000, position_ms: int = 5_000,
               width: int = 1000):
    lane = EffectLane("caption", "캡션", "#abcdef")
    qtbot.addWidget(lane)
    lane.resize(width, 24)
    lane.set_duration_ms(duration_ms)
    lane.set_position_ms(position_ms)
    return lane


def test_snap_within_threshold_returns_playhead(qtbot):
    """playhead 5000ms 의 ±SNAP_PX 안에 있는 값은 playhead 로 스냅."""
    lane = _make_lane(qtbot, duration_ms=10_000, position_ms=5_000, width=1000)
    # body_w = 1000 - 56 = 944, ms/px = 10000/944 ≈ 10.6, SNAP_PX=8 → ~85ms 임계.
    assert lane._snap_ms_to_playhead(5_050) == 5_000
    assert lane._snap_ms_to_playhead(4_950) == 5_000


def test_snap_beyond_threshold_passes_through(qtbot):
    """임계 밖이면 ms 그대로 통과."""
    lane = _make_lane(qtbot, duration_ms=10_000, position_ms=5_000, width=1000)
    # 200ms 차이는 임계(~85ms) 밖.
    assert lane._snap_ms_to_playhead(5_200) == 5_200
    assert lane._snap_ms_to_playhead(4_800) == 4_800


def test_snap_disabled_when_duration_zero(qtbot):
    """duration=0 이면 스냅 비활성 (division by zero 방어)."""
    lane = EffectLane("caption", "x", "#fff")
    qtbot.addWidget(lane)
    lane.resize(1000, 24)
    lane.set_duration_ms(0)
    lane.set_position_ms(0)
    assert lane._snap_ms_to_playhead(123) == 123


def test_snap_pair_move_snaps_nearer_edge_and_shifts_other(qtbot):
    """이동(move) — playhead 근처 edge 스냅 + 반대편 edge 같은 양만큼 평행 이동."""
    lane = _make_lane(qtbot, duration_ms=10_000, position_ms=5_000, width=1000)
    # in=5050 (스냅 대상), out=7050. in→5000 으로 50ms shift, out 도 같이 -50 → 7000.
    new_in, new_out = lane._snap_pair_to_playhead(5_050, 7_050)
    assert new_in == 5_000
    assert new_out == 7_000


def test_snap_pair_move_no_snap_when_neither_edge_close(qtbot):
    """양쪽 edge 모두 임계 밖이면 그대로."""
    lane = _make_lane(qtbot, duration_ms=10_000, position_ms=5_000, width=1000)
    new_in, new_out = lane._snap_pair_to_playhead(2_000, 4_000)
    assert (new_in, new_out) == (2_000, 4_000)


def test_snap_pair_move_prefers_nearer_edge(qtbot):
    """양쪽 모두 임계 안이지만 in 이 더 가까우면 in 기준 스냅."""
    lane = _make_lane(qtbot, duration_ms=10_000, position_ms=5_000, width=1000)
    # 둘 다 ±20ms (둘 다 임계 안). in=4980 가 더 가까움 → in→5000 으로 +20 shift.
    new_in, new_out = lane._snap_pair_to_playhead(4_980, 5_020)
    assert new_in == 5_000
    # out 도 같이 +20 → 5040.
    assert new_out == 5_040
