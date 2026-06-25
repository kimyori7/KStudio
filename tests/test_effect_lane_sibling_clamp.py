"""EffectLane._clamp_against_siblings — 같은 row 이웃에 딱 붙기(flush) 클램프.

2026-06-23 사용자 보고: "배속을 드래그로 옮기다가 다른 배속 옆에 드롭하면 조금이라도
붙으면 위치가 원복되어버려. 옆에 딱 붙으면 좋겠어." 원인: 겹치면 controller 가 거부
→ 원위치 resync. 수정: 드래그 중 이웃 edge 에 딱 붙도록 클램프(폭 보존, 넘지 못함).
"""
from __future__ import annotations

from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.effect_lane import EffectLane


def _lane(qtbot, effs, duration_ms: int = 10_000):
    lane = EffectLane("speed", "배속", "#8b5cf6")
    qtbot.addWidget(lane)
    lane.set_duration_ms(duration_ms)
    lane.set_effects(effs)
    return lane


def test_move_clamps_flush_against_right_sibling(qtbot):
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5)
    lane = _lane(qtbot, [a, b])
    # a(폭 2000)를 오른쪽으로 끌어 b 와 겹치려 함 → b.in(5000)에 딱 붙음.
    out = lane._clamp_against_siblings("move", 4500, 6500,
                                       drag_id=a.id, orig_in=1000, orig_out=3000)
    assert out == (3000, 5000)


def test_move_clamps_flush_against_left_sibling(qtbot):
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5)
    lane = _lane(qtbot, [a, b])
    # b(폭 3000)를 왼쪽으로 끌어 a 와 겹치려 함 → a.out(3000)에 딱 붙음.
    out = lane._clamp_against_siblings("move", 2500, 5500,
                                       drag_id=b.id, orig_in=5000, orig_out=8000)
    assert out == (3000, 6000)


def test_move_no_sibling_in_path_unchanged(qtbot):
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    lane = _lane(qtbot, [a])
    out = lane._clamp_against_siblings("move", 4000, 6000,
                                       drag_id=a.id, orig_in=1000, orig_out=3000)
    assert out == (4000, 6000)


def test_left_edge_clamps_at_left_sibling(qtbot):
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5)
    lane = _lane(qtbot, [a, b])
    # b 의 왼쪽 핸들을 왼쪽으로 끌어 a 위로 침범 → a.out(3000)에서 멈춤.
    out = lane._clamp_against_siblings("left", 2000, 8000,
                                       drag_id=b.id, orig_in=5000, orig_out=8000)
    assert out == (3000, 8000)


def test_right_edge_clamps_at_right_sibling(qtbot):
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5)
    lane = _lane(qtbot, [a, b])
    # a 의 오른쪽 핸들을 오른쪽으로 끌어 b 위로 침범 → b.in(5000)에서 멈춤.
    out = lane._clamp_against_siblings("right", 1000, 6000,
                                       drag_id=a.id, orig_in=1000, orig_out=3000)
    assert out == (1000, 5000)


def test_different_track_idx_is_not_a_sibling(qtbot):
    """track_idx 가 다르면 같은 type 이라도 이웃이 아니다(겹침 허용) → 클램프 안 함."""
    from dataclasses import replace
    a = SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0)
    b = replace(SpeedEffect(in_ms=5000, out_ms=8000, rate=0.5), track_idx=1)
    lane = _lane(qtbot, [a, b])
    # a(track 0)를 b(track 1) 위로 끌어도 b 는 이웃 아님 → 그대로 통과.
    out = lane._clamp_against_siblings("move", 4500, 6500,
                                       drag_id=a.id, orig_in=1000, orig_out=3000,
                                       track_idx=0)
    assert out == (4500, 6500)
