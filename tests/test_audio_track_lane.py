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


def test_mute_button_icon_reflects_state(qtbot):
    """버튼이 현재 소리 상태를 SVG 아이콘으로 보여준다 (이모지 X — tofu 방지).

    소리 켜짐 = volume-2, 음소거 = volume-x. 이모지 텍스트는 일부 Windows/Qt 환경에서
    글리프가 없어 □(tofu)로 렌더되므로 컨트롤바와 같은 SVG 아이콘을 쓴다.
    """
    from screen_recorder.ui.video.audio_track_lane import AudioTrackLane
    lane = AudioTrackLane()
    qtbot.addWidget(lane)
    # 기본 = 소리 켜짐 → volume-2, 실제 아이콘 설정 + 이모지 텍스트 미사용.
    assert lane._current_mute_icon == "volume-2"
    assert lane._mute_btn.text() == ""
    assert not lane._mute_btn.icon().isNull()
    # 음소거 → volume-x
    lane.set_muted(True)
    assert lane._current_mute_icon == "volume-x"
    # 다시 켜기 → volume-2
    lane.set_muted(False)
    assert lane._current_mute_icon == "volume-2"
    # 클릭 토글도 아이콘 갱신 (켜짐 → 음소거).
    lane._mute_btn.click()
    assert lane._current_mute_icon == "volume-x"


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
