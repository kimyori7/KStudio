from screen_recorder.ui.audio.audio_edit_geometry import (
    ms_to_x, x_to_ms, add_cut, remove_cut_at, keep_intervals, playback_skip_target,
)


def test_playback_skip_target():
    keep = [(1000, 3000), (5000, 8000)]
    assert playback_skip_target(2000, keep) is None   # 살아있는 구간 → 그대로
    assert playback_skip_target(500, keep) == 1000     # 앞 트림 → 첫 keep 시작
    assert playback_skip_target(4000, keep) == 5000    # 중간 컷 → 다음 keep
    assert playback_skip_target(8000, keep) == -1      # 끝 지남 → 정지
    assert playback_skip_target(9000, keep) == -1
    assert playback_skip_target(0, []) is None         # keep 없으면 건너뛰기 없음


def test_ms_x_roundtrip():
    assert x_to_ms(ms_to_x(5000, total_ms=10000, width=800),
                   total_ms=10000, width=800) == 5000


def test_x_to_ms_clamps():
    assert x_to_ms(-50, total_ms=10000, width=800) == 0
    assert x_to_ms(99999, total_ms=10000, width=800) == 10000


def test_add_cut_merges_overlapping_and_sorts():
    cuts = add_cut([(2000, 3000)], (2500, 4000))
    assert cuts == [(2000, 4000)]
    cuts = add_cut(cuts, (100, 500))
    assert cuts == [(100, 500), (2000, 4000)]


def test_add_cut_ignores_zero_width():
    assert add_cut([], (1000, 1000)) == []


def test_add_cut_normalizes_reversed_drag():
    assert add_cut([], (4000, 2000)) == [(2000, 4000)]


def test_remove_cut_at_drops_the_region_under_ms():
    cuts = [(1000, 2000), (4000, 5000)]
    assert remove_cut_at(cuts, 1500) == [(4000, 5000)]
    assert remove_cut_at(cuts, 9999) == cuts


def test_keep_intervals_applies_trim_then_cuts():
    keep = keep_intervals(trim_in_ms=1000, trim_out_ms=9000, total_ms=10000,
                          cuts=[(3000, 4000)])
    assert keep == [(1000, 3000), (4000, 9000)]


def test_keep_intervals_trim_out_zero_means_end():
    keep = keep_intervals(trim_in_ms=0, trim_out_ms=0, total_ms=8000, cuts=[])
    assert keep == [(0, 8000)]


def test_keep_intervals_cut_outside_trim_ignored():
    keep = keep_intervals(trim_in_ms=2000, trim_out_ms=6000, total_ms=10000,
                          cuts=[(0, 1000), (8000, 9000)])
    assert keep == [(2000, 6000)]
