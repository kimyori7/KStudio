"""클립 배치 규칙 — 좁은 빈칸에 놓으면 뒤 클립을 밀어 끼워 넣는다.

2026-08-19 사용자 보고: "빈칸 크기 작으면 맨뒤로 다시 날아가버리는데 비집고 들어가게
해줘". 이전 규칙은 놓은 자리에 안 들어가면 트랙 맨 뒤로 보냈다.

Qt 없는 순수 함수라 위젯 없이 그대로 검증한다.
"""
from screen_recorder.ui.video.clip_placement import (
    MoveOutcome, apply_push, free_intervals, plan_placement, placement_note,
)


class _Seg:
    """start_ms / end_ms / id 만 있으면 되는 최소 대역 — VideoSegment 대신."""

    def __init__(self, start_ms: int, end_ms: int, id: str = "") -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.id = id


# ---------- 빈 구간 목록 ----------
def test_free_intervals_includes_zero_width_seams():
    """맞닿은 두 클립 사이의 폭 0 이음매도 후보다 — 거기 끼워 넣으려는 의도가 흔하다."""
    ivs = free_intervals([_Seg(0, 5000), _Seg(5000, 10_000)])
    assert ivs == [(0, 0), (5000, 5000), (10_000, None)]


def test_free_intervals_last_is_unbounded():
    assert free_intervals([_Seg(0, 3000)])[-1] == (3000, None)


def test_free_intervals_on_empty_track():
    assert free_intervals([]) == [(0, None)]


# ---------- 핵심: 좁은 빈칸에 끼워 넣기 ----------
def test_narrow_gap_pushes_following_clips():
    """1초 빈칸에 5초 클립을 놓으면 그 자리에 들어가고 뒤가 4초 밀린다."""
    track = [_Seg(0, 10_000, "c1"), _Seg(11_000, 30_000, "c2"), _Seg(30_000, 50_000, "c3")]
    plan = plan_placement(track, 10_200, 5000)
    assert plan.start_ms == 10_000, "빈칸 시작에 들어간다"
    assert plan.push_from_ms == 11_000
    assert plan.push_delta_ms == 4000, "5초 - 빈칸 1초"
    assert plan.pushes


def test_narrow_gap_never_falls_back_to_track_end():
    """회귀 방지 — 예전에는 이 경우 맨 뒤(50000) 로 날아갔다."""
    track = [_Seg(0, 10_000), _Seg(11_000, 30_000), _Seg(30_000, 50_000)]
    assert plan_placement(track, 10_200, 5000).start_ms < 50_000


def test_push_targets_only_clips_at_or_after_the_gap():
    track = [_Seg(0, 10_000, "c1"), _Seg(11_000, 30_000, "c2"), _Seg(30_000, 50_000, "c3")]
    plan = plan_placement(track, 10_200, 5000)
    moved = apply_push(track, plan)
    assert moved == [(1, 15_000), (2, 34_000)], "c1 은 그대로, 뒤 둘만 4초씩"


def test_push_skips_the_clip_being_moved():
    """왼쪽 빈칸으로 옮기는 클립 자신은 밀림 대상에서 빠진다 (자리는 이미 정해졌다)."""
    track = [_Seg(0, 10_000, "c1"), _Seg(11_000, 30_000, "c2"), _Seg(30_000, 50_000, "x")]
    plan = plan_placement([s for s in track if s.id != "x"], 10_200, 5000)
    assert [i for i, _ in apply_push(track, plan, exclude_id="x")] == [1]


def test_packed_track_seam_pushes_everything_after():
    """빈칸이 아예 없는 트랙 — 이음매에 넣고 그 뒤 전부를 클립 길이만큼 민다."""
    track = [_Seg(0, 5000, "a"), _Seg(5000, 10_000, "b")]
    plan = plan_placement(track, 5100, 3000)
    assert plan.start_ms == 5000
    assert plan.push_from_ms == 5000 and plan.push_delta_ms == 3000
    assert apply_push(track, plan) == [(1, 8000)]


# ---------- 넓은 빈칸 / 제자리: 밀지 않는다 ----------
def test_wide_gap_keeps_free_position():
    """빈칸이 클립보다 넓으면 놓은 지점 그대로 — 자유 배치는 유지된다."""
    plan = plan_placement([_Seg(0, 5000), _Seg(20_000, 25_000)], 9000, 5000)
    assert plan.start_ms == 9000
    assert not plan.pushes


def test_small_drag_onto_neighbour_snaps_back_without_pushing():
    """살짝 끌어 이웃에 겹친 정도로는 이웃을 밀지 않는다 — 원래 자리로 돌아간다.

    자기가 비우는 자리도 빈칸 후보이기 때문에 성립한다.
    """
    plan = plan_placement([_Seg(5000, 10_000, "b")], 3000, 5000)
    assert plan.start_ms == 0
    assert not plan.pushes


def test_dragging_past_neighbour_lands_after_it():
    plan = plan_placement([_Seg(5000, 10_000, "b")], 6000, 5000)
    assert plan.start_ms == 10_000
    assert not plan.pushes


def test_empty_track_keeps_target():
    assert plan_placement([], 7000, 3000).start_ms == 7000


def test_negative_target_clamps_to_zero():
    assert plan_placement([], -500, 3000).start_ms == 0


def test_apply_push_returns_nothing_when_not_pushing():
    plan = plan_placement([], 7000, 3000)
    assert apply_push([_Seg(0, 1000)], plan) == []


# ---------- 사용자 안내 문구 ----------
def test_note_reports_push():
    note = placement_note(MoveOutcome(True, 10_000, 3, 4000), 10_200)
    assert "3개" in note and "4.0초" in note


def test_note_reports_shift_when_landing_elsewhere():
    assert "이동" in placement_note(MoveOutcome(True, 40_000), 9000)


def test_note_is_empty_when_landed_as_requested():
    assert placement_note(MoveOutcome(True, 9000), 9000) == ""
