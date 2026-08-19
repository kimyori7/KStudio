"""클립을 좁은 빈칸으로 끌어 놓으면 뒤 클립들을 밀어 끼워 넣는다 (EditController).

2026-08-19 사용자 요청: "빈칸 크기 작으면 맨뒤로 다시 날아가버리는데 비집고 들어가게
해줘". 배치 계산 자체는 tests/test_clip_placement.py 가 다루고, 여기서는 사이드카에
실제로 어떻게 반영되는지 — 밀린 클립, 따라오는 효과, undo 단위 — 를 본다.
"""
from pathlib import Path

import pytest

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.edit_controller import EditController


@pytest.fixture
def video(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * 200_000)
    return p


@pytest.fixture
def ec(qtbot, video, tmp_path) -> EditController:
    """트랙: c1 [0,10000) — 빈칸 1초 — c2 [11000,21000) — c3 [21000,31000) — x [40000,45000)

    x 가 옮길 클립 (5초). c2/c3 사이엔 빈칸이 없어 예전 규칙에선 x 가 맨 뒤로 갔다.
    """
    c = EditController(video, tmp_path / "sidecars")
    c.ensure_default_track(source_duration_ms=10_000)     # c1 [0,10000)
    for start, dur, name in ((11_000, 10_000, "c2"), (21_000, 10_000, "c3"),
                             (40_000, 5000, "x")):
        c.insert_segment(at_idx=99,
                         segment=VideoSegment(src=f"{name}.mp4", id=name,
                                              src_duration_ms=dur, start_ms=start))
    return c


def _by_id(c: EditController, sid: str) -> VideoSegment:
    return next(s for s in c.sidecar().video_track if s.id == sid)


def test_dropping_into_narrow_gap_inserts_and_pushes(ec):
    """1초 빈칸에 5초 클립을 놓으면 빈칸 시작에 들어가고 뒤가 4초씩 밀린다."""
    out = ec.set_segment_start("x", 10_200)
    assert out.moved
    assert _by_id(ec, "x").start_ms == 10_000
    assert _by_id(ec, "c2").start_ms == 15_000
    assert _by_id(ec, "c3").start_ms == 25_000
    assert out.pushed_count == 2 and out.push_delta_ms == 4000


def test_dropping_into_narrow_gap_does_not_fly_to_track_end(ec):
    """회귀 방지 — 예전에는 들어갈 자리를 못 찾아 트랙 맨 뒤(45000) 로 갔다."""
    ec.set_segment_start("x", 10_200)
    assert _by_id(ec, "x").start_ms < 40_000


def test_no_overlap_after_ripple(ec):
    ec.set_segment_start("x", 10_200)
    track = sorted(ec.sidecar().video_track, key=lambda s: s.start_ms)
    for a, b in zip(track, track[1:]):
        assert a.end_ms <= b.start_ms, f"{a.id} 와 {b.id} 가 겹침"


def test_pushed_clips_carry_their_effects(ec):
    """밀려난 클립 안에 완전히 들어 있던 효과도 같은 양만큼 따라 밀린다."""
    sc = ec.sidecar()
    sc.effects.append(CaptionEffect(in_ms=12_000, out_ms=13_000, text="c2 안"))
    sc.effects.append(CaptionEffect(in_ms=500, out_ms=900, text="c1 안 — 안 밀림"))
    ec.update_sidecar(sc)

    ec.set_segment_start("x", 10_200)
    moved = next(e for e in ec.sidecar().effects if e.text == "c2 안")
    stayed = next(e for e in ec.sidecar().effects if e.text.startswith("c1"))
    assert (moved.in_ms, moved.out_ms) == (16_000, 17_000), "c2 와 같이 4초"
    assert (stayed.in_ms, stayed.out_ms) == (500, 900), "빈칸 앞 클립은 그대로"


def test_ripple_is_a_single_undo_step(ec):
    """옮김 + 밀림이 Ctrl+Z 한 번에 통째로 되돌아간다."""
    ec.set_segment_start("x", 10_200)
    assert ec.undo() is True
    assert _by_id(ec, "x").start_ms == 40_000
    assert _by_id(ec, "c2").start_ms == 11_000
    assert _by_id(ec, "c3").start_ms == 21_000


def test_wide_gap_move_reports_no_push(ec):
    """넉넉한 자리로 옮기면 아무도 밀지 않는다."""
    out = ec.set_segment_start("x", 60_000)
    assert out.moved and out.pushed_count == 0
    assert _by_id(ec, "x").start_ms == 60_000


def test_move_to_same_place_is_a_no_op(ec):
    assert ec.set_segment_start("x", 40_000).moved is False


def test_unknown_id_is_a_no_op(ec):
    assert ec.set_segment_start("없는id", 1000).moved is False


# ---------- 붙여넣기도 같은 규칙 ----------
def test_repeated_paste_into_packed_track_never_overlaps(ec):
    """촘촘한 트랙에 연달아 붙여넣어도 겹치지 않고 매번 자리를 만든다.

    붙여넣기는 밀기 계산에서 제외할 id 가 없다(새 클립이라 트랙에 아직 없다). 그 전제가
    깨지면 밀려난 클립 위에 새 클립이 얹힌다 — 그래서 여기서 겹침을 직접 확인한다.
    """
    for _ in range(3):
        out = ec.paste_clip(
            VideoSegment(src="p.mp4", src_duration_ms=4000), (), at_ms=5000)
        assert out.moved

    track = sorted(ec.sidecar().video_track, key=lambda s: s.start_ms)
    for a, b in zip(track, track[1:]):
        assert a.end_ms <= b.start_ms, f"{a.id} 와 {b.id} 가 겹침"
    assert len(track) == 7, "원래 4개 + 붙여넣은 3개"


def test_paste_into_narrow_gap_lands_there_not_at_track_end(ec):
    """회귀 방지 — 예전에는 인디케이터가 어디에 있든 트랙 맨 뒤에 붙었다."""
    out = ec.paste_clip(
        VideoSegment(src="p.mp4", src_duration_ms=4000), (), at_ms=10_200)
    assert out.start_ms == 10_000
    assert out.pushed_count > 0
