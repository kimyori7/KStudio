from screen_recorder.effects.segment import VideoSegment


def _seg(src, dur, start):
    return VideoSegment(src=src, src_in_ms=0, src_out_ms=0,
                        src_duration_ms=dur, start_ms=start)


def test_lane_api_and_mute_signal(qtbot):
    from screen_recorder.ui.video.audio_track_lane import AudioTrackLane
    lane = AudioTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 44)
    lane.set_duration_ms(2000)
    lane.set_segments([_seg("a.mp4", 1000, 0), _seg("a.mp4", 1000, 1000)])
    lane.set_peaks("a.mp4", [0.5] * 100)
    lane.set_muted(True)
    got = []
    lane.mute_toggled.connect(lambda m: got.append(m))
    lane._mute_btn.click()
    assert got and isinstance(got[0], bool)


def test_lane_paints_without_crash(qtbot):
    from PySide6.QtGui import QPixmap
    from screen_recorder.ui.video.audio_track_lane import AudioTrackLane
    lane = AudioTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 44)
    lane.set_duration_ms(1000)
    lane.set_segments([_seg("a.mp4", 1000, 0)])
    lane.set_peaks("a.mp4", [])   # 소리 없음 경로
    pm = QPixmap(400, 44)
    lane.render(pm)   # paintEvent 크래시 안 나면 통과
