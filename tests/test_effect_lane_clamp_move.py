"""EffectLane._clamp_move_to_bounds — 평행 이동 드래그 시 폭 보존.

2026-05-19 사용자 보고: "배속 같은 바 누르고 왼쪽으로 드래그하면 왼쪽 끝에 도달
하면 멈춰야되는데 오른쪽 끝이 줄어듦."

기존 버그: drag move 후 `new_in = max(0, new_in)` / `new_out = max(0, new_out)` 가
독립 클램프 → in 만 0 에 막히고 out 은 그대로 줄어들어 폭이 좁아짐.

수정: 평행 이동 단위로 클램프 — 한쪽 경계 도달 시 반대편을 같은 만큼 보정해 폭 유지.
"""
from __future__ import annotations

from screen_recorder.ui.video.effect_lane import EffectLane


def _make_lane(qtbot, duration_ms: int = 10_000):
    lane = EffectLane("caption", "캡션", "#abcdef")
    qtbot.addWidget(lane)
    lane.set_duration_ms(duration_ms)
    return lane


def test_move_within_bounds_no_change(qtbot):
    """경계 안에서의 이동은 그대로 통과."""
    lane = _make_lane(qtbot)
    assert lane._clamp_move_to_bounds(2000, 5000) == (2000, 5000)


def test_move_in_below_zero_shifts_both_to_keep_width(qtbot):
    """왼쪽으로 드래그해 in 이 음수 → in=0 + out 평행 보정 → 폭 유지."""
    lane = _make_lane(qtbot, duration_ms=10_000)
    # 폭 2000, 왼쪽 끝을 -500 까지 끌면 → (0, 2000) 로 보정 (out 도 평행 이동).
    assert lane._clamp_move_to_bounds(-500, 1500) == (0, 2000)


def test_move_out_above_duration_shifts_both_to_keep_width(qtbot):
    """오른쪽으로 드래그해 out 이 duration 초과 → out=duration + in 평행 보정."""
    lane = _make_lane(qtbot, duration_ms=10_000)
    # 폭 2000, 오른쪽 끝을 11000 까지 끌면 → (8000, 10000).
    assert lane._clamp_move_to_bounds(9000, 11000) == (8000, 10_000)


def test_move_wider_than_duration_clamped_to_full(qtbot):
    """효과 폭이 영상보다 큰 드문 경우 — 전체 범위로 클램프 (폭 손실 불가피)."""
    lane = _make_lane(qtbot, duration_ms=5000)
    # 폭 8000, 영상 5000 — (0, 5000) 으로 클램프.
    assert lane._clamp_move_to_bounds(-1000, 7000) == (0, 5000)


def test_move_in_exactly_zero_unchanged(qtbot):
    """경계 정확히 도달 — 0 그대로."""
    lane = _make_lane(qtbot)
    assert lane._clamp_move_to_bounds(0, 3000) == (0, 3000)
