"""같은 종류 시간 겹침 검사."""
from screen_recorder.effects.overlap import overlaps_existing
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect


def test_no_existing_returns_false():
    cand = CaptionEffect(in_ms=0, out_ms=1000, text="x")
    assert overlaps_existing([], cand) is False


def test_different_type_does_not_overlap():
    existing = [SpeedEffect(in_ms=0, out_ms=10000, rate=2.0)]
    cand = CaptionEffect(in_ms=2000, out_ms=3000, text="x")
    assert overlaps_existing(existing, cand) is False


def test_same_type_disjoint_no_overlap():
    existing = [CaptionEffect(in_ms=0, out_ms=1000, text="a")]
    cand = CaptionEffect(in_ms=1000, out_ms=2000, text="b")  # touch but no overlap
    assert overlaps_existing(existing, cand) is False


def test_same_type_partial_overlap():
    existing = [CaptionEffect(in_ms=0, out_ms=2000, text="a")]
    cand = CaptionEffect(in_ms=1000, out_ms=3000, text="b")
    assert overlaps_existing(existing, cand) is True


def test_same_type_full_contain_overlap():
    existing = [CaptionEffect(in_ms=0, out_ms=10000, text="a")]
    cand = CaptionEffect(in_ms=2000, out_ms=3000, text="b")
    assert overlaps_existing(existing, cand) is True


def test_self_excluded_by_id():
    """같은 id (자기 자신) 는 겹침으로 안 봄 — 시간 이동 시 검증에 필요."""
    existing = [CaptionEffect(id="me", in_ms=0, out_ms=2000, text="a")]
    cand = CaptionEffect(id="me", in_ms=1000, out_ms=3000, text="a")
    assert overlaps_existing(existing, cand) is False
