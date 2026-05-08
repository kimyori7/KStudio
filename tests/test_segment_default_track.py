"""사이드카 로드 시 video_track 이 비어 있으면 source 영상 1개 segment 로 자동 채움."""
from screen_recorder.effects import Sidecar
from screen_recorder.effects.sidecar import ensure_default_track
from screen_recorder.effects.segment import VideoSegment


def test_ensure_default_track_creates_single_segment():
    sc = Sidecar(source_path="/path/to/x.mp4", source_hash="h")
    ensure_default_track(sc, source_duration_ms=10000)
    assert len(sc.video_track) == 1
    seg = sc.video_track[0]
    assert seg.src == "/path/to/x.mp4"
    assert seg.src_in_ms == 0
    assert seg.src_out_ms == 0
    assert seg.src_duration_ms == 10000
    assert seg.media_kind == "video"


def test_ensure_default_track_noop_if_already_has_segments():
    sc = Sidecar(source_path="x.mp4", source_hash="h")
    sc.video_track.append(VideoSegment(src="other.mp4"))
    ensure_default_track(sc, source_duration_ms=5000)
    assert len(sc.video_track) == 1
    assert sc.video_track[0].src == "other.mp4"


def test_ensure_default_track_with_unknown_duration_creates_with_zero():
    """duration_ms 가 0 이거나 음수일 때도 segment 만들고 src_duration_ms = 0 으로."""
    sc = Sidecar(source_path="x.mp4", source_hash="h")
    ensure_default_track(sc, source_duration_ms=0)
    assert len(sc.video_track) == 1
    assert sc.video_track[0].src_duration_ms == 0


def test_ensure_default_track_negative_duration_clamped_to_zero():
    sc = Sidecar(source_path="x.mp4", source_hash="h")
    ensure_default_track(sc, source_duration_ms=-1)
    assert sc.video_track[0].src_duration_ms == 0
