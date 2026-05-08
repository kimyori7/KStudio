"""VideoSegment — 트랙의 한 클립 (영상/이미지/GIF 의 일부분)."""
import pytest
from screen_recorder.effects.segment import VideoSegment


def test_segment_default_id_is_unique():
    a = VideoSegment(src="a.mp4")
    b = VideoSegment(src="a.mp4")
    assert a.id != b.id
    assert len(a.id) > 0


def test_segment_explicit_id_preserved():
    s = VideoSegment(id="fixed-123", src="a.mp4")
    assert s.id == "fixed-123"


def test_segment_default_fields():
    s = VideoSegment(src="a.mp4")
    assert s.src == "a.mp4"
    assert s.src_in_ms == 0
    assert s.src_out_ms == 0
    assert s.src_duration_ms == 0
    assert s.media_kind == "video"
    assert s.image_duration_ms == 3000
    assert s.effects == []


def test_segment_invalid_src_in_negative_raises():
    with pytest.raises(ValueError):
        VideoSegment(src="a.mp4", src_in_ms=-1)


def test_segment_invalid_src_out_lt_in_raises():
    with pytest.raises(ValueError):
        VideoSegment(src="a.mp4", src_in_ms=2000, src_out_ms=1500)


def test_segment_invalid_media_kind_raises():
    with pytest.raises(ValueError):
        VideoSegment(src="a.mp4", media_kind="audio")


def test_segment_image_kind_with_zero_duration_raises():
    with pytest.raises(ValueError):
        VideoSegment(src="a.png", media_kind="image", image_duration_ms=0)


def test_segment_duration_video():
    """영상: src_out_ms - src_in_ms (or src_duration_ms 까지)."""
    s = VideoSegment(src="a.mp4", src_in_ms=1000, src_out_ms=5000)
    assert s.duration_ms == 4000


def test_segment_duration_video_with_zero_out():
    """src_out_ms=0 → src_duration_ms - src_in_ms."""
    s = VideoSegment(
        src="a.mp4", src_in_ms=1000, src_out_ms=0, src_duration_ms=10000
    )
    assert s.duration_ms == 9000


def test_segment_duration_image():
    """이미지: image_duration_ms."""
    s = VideoSegment(
        src="a.png", media_kind="image", image_duration_ms=5000
    )
    assert s.duration_ms == 5000
