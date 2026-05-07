"""CutEffect — 자르기 (단순/구간) + 옵션 영상 끼워넣기 (insert)."""
import pytest

from screen_recorder.effects.types.cut import CutEffect


# ---- 자르기 모드 ----
def test_cut_range_construct():
    """구간 자르기 — in_ms < out_ms."""
    c = CutEffect(in_ms=10000, out_ms=12000)
    assert c.type == "cut"
    assert c.duration_ms == 2000
    assert not c.is_splice
    assert not c.has_insert
    assert c.insert_duration_ms == 0


def test_cut_splice_construct():
    """splice point — in_ms == out_ms 허용."""
    c = CutEffect(in_ms=4000, out_ms=4000)
    assert c.duration_ms == 0
    assert c.is_splice
    assert not c.has_insert


def test_cut_negative_in_ms_rejected():
    with pytest.raises(ValueError, match="in_ms"):
        CutEffect(in_ms=-1, out_ms=100)


def test_cut_out_less_than_in_rejected():
    with pytest.raises(ValueError, match="out_ms"):
        CutEffect(in_ms=200, out_ms=100)


# ---- 영상 끼워넣기 모드 ----
def test_cut_with_insert_construct():
    """잘라내기 + B 영상."""
    c = CutEffect(
        in_ms=4000, out_ms=7000,
        src=r"D:\Clips\intro.mp4",
        src_in_ms=500, src_out_ms=4500,
        src_duration_ms=6000,
        scale_mode="fit",
    )
    assert c.has_insert
    assert c.insert_duration_ms == 4000


def test_cut_insert_until_end():
    """src_out_ms == 0 → src_duration_ms 까지."""
    c = CutEffect(
        in_ms=0, out_ms=0,
        src=r"D:\Clips\b.mp4",
        src_in_ms=1000, src_out_ms=0,
        src_duration_ms=5000,
    )
    assert c.has_insert
    assert c.insert_duration_ms == 4000


def test_cut_invalid_scale_mode_rejected():
    with pytest.raises(ValueError, match="scale_mode"):
        CutEffect(in_ms=0, out_ms=100, src="x", scale_mode="invalid")


def test_cut_invalid_src_in_ms_rejected():
    with pytest.raises(ValueError, match="src_in_ms"):
        CutEffect(in_ms=0, out_ms=100, src="x", src_in_ms=-1)


def test_cut_invalid_src_out_le_in_rejected():
    """src_out_ms 가 양수인데 src_in_ms 보다 작거나 같으면 거부."""
    with pytest.raises(ValueError, match="src_out_ms"):
        CutEffect(in_ms=0, out_ms=100, src="x", src_in_ms=500, src_out_ms=500)


def test_cut_no_insert_default():
    """src 가 비어있으면 has_insert == False, src 관련 검증 통과."""
    c = CutEffect(in_ms=0, out_ms=100)
    assert not c.has_insert
