"""VideoTimeline 안에 VideoTrackLane 이 들어가고 sidecar.video_track 이 표시된다."""
from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.timeline import VideoTimeline


def test_timeline_has_video_track_lane(qtbot):
    tl = VideoTimeline()
    qtbot.addWidget(tl)
    assert tl.video_track_lane is not None


def test_timeline_set_sidecar_propagates_segments(qtbot):
    tl = VideoTimeline()
    qtbot.addWidget(tl)
    seg = VideoSegment(
        src="a.mp4", src_in_ms=0, src_out_ms=5000, src_duration_ms=5000,
    )
    sc = Sidecar(source_path="a.mp4", source_hash="h", video_track=[seg])
    tl.set_sidecar(sc)
    assert len(tl.video_track_lane.segments()) == 1
    assert tl.video_track_lane.segments()[0].id == seg.id


def test_timeline_set_duration_propagates(qtbot):
    tl = VideoTimeline()
    qtbot.addWidget(tl)
    tl.set_duration_ms(12_000)
    assert tl.video_track_lane._duration_ms == 12_000


def test_timeline_edit_mode_shows_track_lane(qtbot):
    tl = VideoTimeline()
    qtbot.addWidget(tl)
    tl.show()
    qtbot.waitExposed(tl)
    # 기본은 OFF — track lane 안 보임.
    assert not tl.video_track_lane.isVisible()
    tl.set_edit_mode(True)
    assert tl.video_track_lane.isVisible()
    tl.set_edit_mode(False)
    assert not tl.video_track_lane.isVisible()
