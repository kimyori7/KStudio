"""effects.timeline — 결합 시간축 매핑 helper.

CutEffect 들이 만드는 결합 시간축에서:
- 어떤 결합 ms 가 어떤 source(main 영상 / B insert) 의 어떤 ms 인지
- 그 역방향 (source ms → 결합 ms)

UI 의존 없음 — 순수 도메인 로직.
"""
from dataclasses import FrozenInstanceError

import pytest

from screen_recorder.effects.timeline import (
    TimelineSegment,
    build_combined_timeline,
    combined_to_source,
    source_to_combined,
)
from screen_recorder.effects.types.cut import CutEffect


def test_timeline_segment_is_frozen():
    """TimelineSegment 는 frozen dataclass — 불변."""
    seg = TimelineSegment(
        combined_start_ms=0, combined_end_ms=1000,
        source="main", source_id=None,
        source_start_ms=0, source_end_ms=1000,
    )
    with pytest.raises(FrozenInstanceError):
        seg.combined_start_ms = 999


# ---------------------------------------------------------------------------
# Task 2: build_combined_timeline
# ---------------------------------------------------------------------------

def _seg(start, end, source, sid, ss, se):
    return TimelineSegment(
        combined_start_ms=start, combined_end_ms=end,
        source=source, source_id=sid,
        source_start_ms=ss, source_end_ms=se,
    )


def test_build_no_cuts_is_single_main_segment():
    """cut 0 개 = main 한 segment, 결합 길이 = 원본 길이."""
    segs = build_combined_timeline(10000, [])
    assert segs == [_seg(0, 10000, "main", None, 0, 10000)]


def test_build_simple_range_cut_no_insert():
    """A 의 3000-6000 자르기, src 비어있음 → main 두 segment, 결합 7000."""
    cut = CutEffect(in_ms=3000, out_ms=6000)
    segs = build_combined_timeline(10000, [cut])
    assert segs == [
        _seg(0, 3000, "main", None, 0, 3000),
        _seg(3000, 7000, "main", None, 6000, 10000),
    ]


def test_build_splice_with_insert():
    """A 의 4000 splice + B 0-3000 → main + insert + main, 결합 13000."""
    cut = CutEffect(
        in_ms=4000, out_ms=4000,
        src="b.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=3000,
    )
    segs = build_combined_timeline(10000, [cut])
    assert segs == [
        _seg(0, 4000, "main", None, 0, 4000),
        _seg(4000, 7000, "insert", cut.id, 0, 3000),
        _seg(7000, 13000, "main", None, 4000, 10000),
    ]


def test_build_range_cut_with_insert():
    """A 의 3000-6000 자르기 + B 0-4000 → main + insert + main, 결합 11000."""
    cut = CutEffect(
        in_ms=3000, out_ms=6000,
        src="b.mp4", src_in_ms=0, src_out_ms=4000, src_duration_ms=4000,
    )
    segs = build_combined_timeline(10000, [cut])
    assert segs == [
        _seg(0, 3000, "main", None, 0, 3000),
        _seg(3000, 7000, "insert", cut.id, 0, 4000),
        _seg(7000, 11000, "main", None, 6000, 10000),
    ]


def test_build_cuts_sorted_by_in_ms():
    """순서 무관하게 입력해도 in_ms 기준 정렬되어 segment 생성."""
    c1 = CutEffect(in_ms=7000, out_ms=8000)  # 뒤
    c2 = CutEffect(in_ms=2000, out_ms=3000)  # 앞
    segs = build_combined_timeline(10000, [c1, c2])
    # 결합: 0~2000 (main 0~2000), 2000~6000 (main 3000~7000, c2 적용 후), 6000~8000 (main 8000~10000, c1 적용 후)
    assert segs == [
        _seg(0, 2000, "main", None, 0, 2000),
        _seg(2000, 6000, "main", None, 3000, 7000),
        _seg(6000, 8000, "main", None, 8000, 10000),
    ]


def test_build_overlapping_cuts_raises():
    """겹치는 cut 은 거부 (Stage 4 검증 정책)."""
    c1 = CutEffect(in_ms=2000, out_ms=5000)
    c2 = CutEffect(in_ms=4000, out_ms=7000)  # 2000-5000 과 겹침
    with pytest.raises(ValueError, match=r"overlap"):
        build_combined_timeline(10000, [c1, c2])


def test_build_splice_at_zero():
    """A 의 0 시점 splice + insert (영상 앞에 prefix)."""
    cut = CutEffect(
        in_ms=0, out_ms=0,
        src="prefix.mp4", src_in_ms=0, src_out_ms=2000, src_duration_ms=2000,
    )
    segs = build_combined_timeline(10000, [cut])
    assert segs == [
        _seg(0, 2000, "insert", cut.id, 0, 2000),
        _seg(2000, 12000, "main", None, 0, 10000),
    ]


def test_build_splice_at_end():
    """A 의 끝 시점 splice + insert (영상 끝에 suffix)."""
    cut = CutEffect(
        in_ms=10000, out_ms=10000,
        src="suffix.mp4", src_in_ms=0, src_out_ms=2000, src_duration_ms=2000,
    )
    segs = build_combined_timeline(10000, [cut])
    assert segs == [
        _seg(0, 10000, "main", None, 0, 10000),
        _seg(10000, 12000, "insert", cut.id, 0, 2000),
    ]


def test_build_insert_only_cut_zero_length_main_remainder():
    """A 0 ms (degenerate — 빈 영상에 splice insert)."""
    cut = CutEffect(
        in_ms=0, out_ms=0,
        src="b.mp4", src_in_ms=0, src_out_ms=1000, src_duration_ms=1000,
    )
    segs = build_combined_timeline(0, [cut])
    # main 0~0 segment 는 빈 segment 라 생략, insert 0~1000 만.
    assert segs == [_seg(0, 1000, "insert", cut.id, 0, 1000)]


# ---------------------------------------------------------------------------
# Task 3: combined_to_source
# ---------------------------------------------------------------------------

@pytest.fixture
def segments_with_insert():
    """A 의 3000-6000 자르기 + B 0-4000 → main + insert + main, 결합 11000."""
    cut = CutEffect(
        in_ms=3000, out_ms=6000,
        src="b.mp4", src_in_ms=0, src_out_ms=4000, src_duration_ms=4000,
    )
    return build_combined_timeline(10000, [cut]), cut


def test_combined_to_source_in_first_main(segments_with_insert):
    segs, _cut = segments_with_insert
    src, sid, ms = combined_to_source(1500, segs)
    assert src == "main"
    assert sid is None
    assert ms == 1500


def test_combined_to_source_in_insert(segments_with_insert):
    segs, cut = segments_with_insert
    src, sid, ms = combined_to_source(5000, segs)
    assert src == "insert"
    assert sid == cut.id
    assert ms == 2000  # 5000(combined) - 3000(insert start in combined) = 2000 → src_in_ms 0 + 2000


def test_combined_to_source_in_second_main(segments_with_insert):
    segs, _cut = segments_with_insert
    src, sid, ms = combined_to_source(8000, segs)
    assert src == "main"
    assert sid is None
    assert ms == 7000  # 8000 - 7000(second main start in combined) = 1000 → 6000(main start) + 1000


def test_combined_to_source_at_segment_boundary_picks_right(segments_with_insert):
    """경계 ms 는 다음 segment 의 시작점으로 매핑 (start inclusive, end exclusive).

    예: 첫 main 0~3000, insert 3000~7000 일 때 t=3000 은 insert 의 시작점.
    """
    segs, cut = segments_with_insert
    src, sid, ms = combined_to_source(3000, segs)
    assert src == "insert"
    assert sid == cut.id
    assert ms == 0


def test_combined_to_source_at_end_returns_last_segment_end():
    segs = build_combined_timeline(10000, [])
    src, sid, ms = combined_to_source(10000, segs)
    # t == 결합 끝 ms 는 'main 의 end ms' 로 clamp (사용자 시크 시 영상 끝).
    assert src == "main"
    assert ms == 10000


def test_combined_to_source_negative_ms_clamps_to_zero():
    segs = build_combined_timeline(10000, [])
    src, sid, ms = combined_to_source(-100, segs)
    assert src == "main"
    assert ms == 0


def test_combined_to_source_empty_segments_raises():
    with pytest.raises(ValueError, match=r"empty"):
        combined_to_source(0, [])


# ---------------------------------------------------------------------------
# Task 4: source_to_combined
# ---------------------------------------------------------------------------

def test_source_to_combined_main_first_part(segments_with_insert):
    segs, _ = segments_with_insert
    assert source_to_combined("main", None, 1500, segs) == 1500


def test_source_to_combined_main_after_cut(segments_with_insert):
    segs, _ = segments_with_insert
    # main 7000 ms 는 cut 적용 후 결합에서 7000 - 3000(잘린 길이) + 4000(B) = 8000
    assert source_to_combined("main", None, 7000, segs) == 8000


def test_source_to_combined_insert(segments_with_insert):
    segs, cut = segments_with_insert
    # insert 의 1000 ms = 결합 4000 ms (insert 시작 3000 + 1000)
    assert source_to_combined("insert", cut.id, 1000, segs) == 4000


def test_source_to_combined_unknown_source_raises():
    segs = build_combined_timeline(10000, [])
    with pytest.raises(ValueError, match=r"no segment"):
        source_to_combined("insert", "unknown-id", 0, segs)


def test_source_to_combined_main_inside_cut_raises():
    """main 의 잘린 구간 (3000~6000) 의 ms 는 결합에 없음 → ValueError."""
    cut = CutEffect(
        in_ms=3000, out_ms=6000,
        src="b.mp4", src_in_ms=0, src_out_ms=4000, src_duration_ms=4000,
    )
    segs = build_combined_timeline(10000, [cut])
    with pytest.raises(ValueError, match=r"no segment"):
        source_to_combined("main", None, 4500, segs)  # 잘린 main 구간
