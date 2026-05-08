"""EditController segment 단위 API — split / insert / delete / move / update."""
from pathlib import Path

import pytest

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.sidecar import ensure_default_track
from screen_recorder.ui.video.edit_controller import EditController


@pytest.fixture
def video(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * 200_000)
    return p


@pytest.fixture
def ec_with_track(qtbot, video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    ec.ensure_default_track(source_duration_ms=10_000)
    return ec


def test_split_segment_creates_two_segments(qtbot, ec_with_track):
    """splice point 가 0 < at_local_ms < segment.duration 인 경우 둘로 쪼갬."""
    sc = ec_with_track.sidecar()
    orig_id = sc.video_track[0].id
    orig_dur = sc.video_track[0].src_duration_ms
    # at_local_ms = 4000 → 0~4000 / 4000~10000 두 segment.
    with qtbot.waitSignal(ec_with_track.sidecar_replaced, timeout=500):
        ok = ec_with_track.split_segment(orig_id, at_local_ms=4000)
    assert ok is True
    track = ec_with_track.sidecar().video_track
    assert len(track) == 2
    # 첫 segment: src_in=0, src_out=4000 (or duration sentinel 0 → 명시 4000).
    assert track[0].src_in_ms == 0
    assert track[0].src_out_ms == 4000
    # 둘째 segment: src_in=4000, src_out=원본 src_out (또는 duration).
    assert track[1].src_in_ms == 4000
    # 두 segment 의 src 는 같음.
    assert track[0].src == track[1].src
    # id 는 둘 다 새것이거나 첫 번째가 원본 id 유지 (구현 자유) — 합쳐서 2개 unique.
    assert track[0].id != track[1].id


def test_split_segment_rejects_out_of_range(ec_with_track):
    sc = ec_with_track.sidecar()
    sid = sc.video_track[0].id
    # 0 또는 duration 동일 — 분할 불가.
    assert ec_with_track.split_segment(sid, at_local_ms=0) is False
    assert ec_with_track.split_segment(sid, at_local_ms=10_000) is False
    assert ec_with_track.split_segment(sid, at_local_ms=-100) is False
    # 너무 짧은 한 쪽 (50ms 폭) 도 거부 — 최소 100ms.
    assert ec_with_track.split_segment(sid, at_local_ms=50) is False
    assert ec_with_track.split_segment(sid, at_local_ms=9_950) is False


def test_split_segment_unknown_id_no_op(ec_with_track):
    assert ec_with_track.split_segment("not-there", at_local_ms=2000) is False


def test_insert_segment_at_index(qtbot, ec_with_track):
    sc = ec_with_track.sidecar()
    # 처음엔 segment 1개.
    new_seg = VideoSegment(
        src="other.mp4", src_duration_ms=3000,
    )
    with qtbot.waitSignal(ec_with_track.sidecar_replaced, timeout=500):
        ok = ec_with_track.insert_segment(at_idx=1, segment=new_seg)
    assert ok is True
    track = ec_with_track.sidecar().video_track
    assert len(track) == 2
    assert track[1].id == new_seg.id


def test_insert_segment_at_zero_prepends(qtbot, ec_with_track):
    new_seg = VideoSegment(src="prefix.mp4", src_duration_ms=2000)
    ec_with_track.insert_segment(at_idx=0, segment=new_seg)
    track = ec_with_track.sidecar().video_track
    assert track[0].id == new_seg.id
    assert len(track) == 2


def test_insert_segment_clamps_index(ec_with_track):
    """음수 idx 는 0, 너무 큰 idx 는 끝에."""
    a = VideoSegment(src="a.mp4", src_duration_ms=1000)
    b = VideoSegment(src="b.mp4", src_duration_ms=1000)
    ec_with_track.insert_segment(at_idx=-5, segment=a)
    assert ec_with_track.sidecar().video_track[0].id == a.id
    ec_with_track.insert_segment(at_idx=999, segment=b)
    assert ec_with_track.sidecar().video_track[-1].id == b.id


def test_delete_segment_by_id(qtbot, ec_with_track):
    new_seg = VideoSegment(src="other.mp4", src_duration_ms=3000)
    ec_with_track.insert_segment(at_idx=1, segment=new_seg)
    sc = ec_with_track.sidecar()
    assert len(sc.video_track) == 2
    with qtbot.waitSignal(ec_with_track.sidecar_replaced, timeout=500):
        ok = ec_with_track.delete_segment(new_seg.id)
    assert ok is True
    track = ec_with_track.sidecar().video_track
    assert len(track) == 1
    assert track[0].id != new_seg.id


def test_delete_segment_unknown_id_no_op(ec_with_track):
    assert ec_with_track.delete_segment("not-there") is False


def test_move_segment_swaps_order(qtbot, ec_with_track):
    a = VideoSegment(src="a.mp4", src_duration_ms=1000)
    ec_with_track.insert_segment(at_idx=1, segment=a)
    track = ec_with_track.sidecar().video_track
    assert track[1].id == a.id
    # 1 → 0 으로 이동.
    with qtbot.waitSignal(ec_with_track.sidecar_replaced, timeout=500):
        ok = ec_with_track.move_segment(from_idx=1, to_idx=0)
    assert ok is True
    track = ec_with_track.sidecar().video_track
    assert track[0].id == a.id


def test_move_segment_invalid_idx(ec_with_track):
    assert ec_with_track.move_segment(from_idx=5, to_idx=0) is False
    assert ec_with_track.move_segment(from_idx=0, to_idx=99) is False


def test_update_segment_replaces_by_id(qtbot, ec_with_track):
    """가장자리 트림처럼 segment 의 src_in/out 만 갱신."""
    from dataclasses import replace
    sc = ec_with_track.sidecar()
    orig = sc.video_track[0]
    updated = replace(orig, src_in_ms=500, src_out_ms=8000)
    with qtbot.waitSignal(ec_with_track.sidecar_replaced, timeout=500):
        ok = ec_with_track.update_segment(updated)
    assert ok is True
    track = ec_with_track.sidecar().video_track
    assert track[0].src_in_ms == 500
    assert track[0].src_out_ms == 8000


def test_undo_after_split_restores_single_segment(qtbot, ec_with_track):
    sid = ec_with_track.sidecar().video_track[0].id
    ec_with_track.split_segment(sid, at_local_ms=4000)
    assert len(ec_with_track.sidecar().video_track) == 2
    ec_with_track.undo()
    assert len(ec_with_track.sidecar().video_track) == 1


def test_undo_after_insert_restores_track(qtbot, ec_with_track):
    new_seg = VideoSegment(src="other.mp4", src_duration_ms=2000)
    ec_with_track.insert_segment(at_idx=1, segment=new_seg)
    assert len(ec_with_track.sidecar().video_track) == 2
    ec_with_track.undo()
    assert len(ec_with_track.sidecar().video_track) == 1
