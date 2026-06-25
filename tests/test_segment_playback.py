"""SegmentPlaybackController — 단일 player + segment 순차 재생 + 갭 지원."""
from unittest.mock import MagicMock

from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.segment_playback import SegmentPlaybackController


def _seg(src: str, start: int, dur: int, sid: str) -> VideoSegment:
    return VideoSegment(
        id=sid, src=src, src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
        start_ms=start,
    )


def _ctrl(*segments: VideoSegment) -> tuple[SegmentPlaybackController, MagicMock]:
    player = MagicMock()
    player.is_playing.return_value = False
    ctrl = SegmentPlaybackController(player)
    sc = Sidecar(source_path="x", source_hash="h", video_track=list(segments))
    ctrl.set_sidecar(sc)
    return ctrl, player


def test_combined_duration_uses_max_end_ms():
    ctrl, _ = _ctrl(_seg("a", 0, 3000, "a"), _seg("b", 3000, 2000, "b"))
    assert ctrl.combined_duration_ms() == 5000


def test_combined_duration_with_gap_uses_max_end_ms():
    """갭이 있어도 마지막 segment 의 end_ms 가 트랙 길이."""
    ctrl, _ = _ctrl(_seg("a", 0, 3000, "a"), _seg("b", 5000, 2000, "b"))
    assert ctrl.combined_duration_ms() == 7000


def test_seek_combined_routes_to_first_segment():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(1000)
    # set_sidecar 가 첫 segment 를 활성 (pre-set) 하므로 첫 시크는 reload 없이 seek 만.
    player.load.assert_not_called()
    player.seek_ms.assert_called_with(1000)
    assert ctrl.active_segment_id == "a"


def test_seek_combined_routes_to_second_segment_with_gap():
    """갭 모델: 두 번째 segment 가 start_ms=5000 부터. 4000 시크 → 갭."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    # 5500 → b 안 (local=500).
    ctrl.seek_combined_ms(5500)
    player.seek_ms.assert_called_with(500)
    assert ctrl.active_segment_id == "b"


def test_seek_into_gap_emits_active_empty_string():
    """갭 위치 시크 시 active_segment_changed 가 빈 문자열 emit."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    received: list[str] = []
    ctrl.active_segment_changed.connect(lambda s: received.append(s))
    ctrl.seek_combined_ms(4000)   # 갭 (3000~5000) 안.
    assert ctrl.active_segment_id is None
    assert "" in received


def test_position_change_emits_combined_ms():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(0)   # a 활성화.
    received: list[int] = []
    ctrl.combined_position_changed.connect(lambda v: received.append(v))
    ctrl.on_main_position_changed(1500)
    assert received[-1] == 1500


def test_position_change_in_second_segment_uses_start_ms_offset():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(3500)   # b 활성화.
    received: list[int] = []
    ctrl.combined_position_changed.connect(lambda v: received.append(v))
    ctrl.on_main_position_changed(800)   # b src local=800.
    # combined = b.start_ms (3000) + 800.
    assert received[-1] == 3800


def test_segment_boundary_auto_advances():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(2999)
    player.load.reset_mock()
    player.seek_ms.reset_mock()
    ctrl.on_main_position_changed(3000)
    assert ctrl.active_segment_id == "b"
    player.load.assert_called_once()
    player.seek_ms.assert_called_with(0)


def test_video_to_video_boundary_holds_last_frame():
    """영상→영상 경계 자동 전환 시 load(hold_last_frame=True) — 회색 깜빡임 방지.

    새 src 를 비동기 로딩하는 동안 surface 를 비우면(clear_frame) 검은/회색 프레임이
    잠깐 뜬다. 이전 클립의 마지막 프레임을 유지하도록 hold_last_frame=True 로 로드.
    """
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(2999)
    player.load.reset_mock()
    ctrl.on_main_position_changed(3000)
    player.load.assert_called_once()
    assert player.load.call_args.kwargs.get("hold_last_frame") is True


def test_source_switch_position_reset_does_not_jump_to_zero():
    """클립 전환 시 setSource 가 동기적으로 position 0 을 보고해도 재생바가 트랙
    처음(0)으로 튀지 않아야 한다.

    QMediaPlayer.setSource(B) 는 새 미디어의 position 을 0 으로 리셋하며
    positionChanged(0) 을 쏜다. _activate_segment 가 _active_idx 를 새 segment 로
    갱신하기 *전에* load() 를 부르면, 그 0 이 아직 옛 segment(A) 기준으로 환산돼
    combined = A.start_ms(=0) → 재생바가 처음으로 튄다. _active_idx 를 먼저 갱신해야 한다.
    """
    ctrl, player = _ctrl(_seg("a.mp4", 0, 2000, "a"), _seg("b.mp4", 2000, 7000, "b"))
    ctrl.seek_combined_ms(1999)   # a 활성 (preset 이라 load 없음)
    emitted: list[int] = []
    ctrl.combined_position_changed.connect(emitted.append)

    # load(=setSource) 호출 순간 player 가 position 0 을 동기적으로 보고하는 상황 모사.
    def _load_side_effect(path, *, hold_last_frame=False):
        ctrl.on_main_position_changed(0)
    player.load.side_effect = _load_side_effect

    ctrl.on_main_position_changed(2000)   # a 끝 → b 로 전환
    assert emitted, "전환 중 combined emit 이 있어야 한다"
    assert min(emitted) >= 2000, f"재생바가 트랙 처음으로 튐: {emitted}"


def test_gap_exit_does_not_hold_last_frame():
    """갭 이탈 후 segment 진입은 hold 하지 않음 — 갭에서 이미 검은 화면을 보여줬고
    이전 영상 프레임은 stale 이므로 정상 clear 로 새 프레임을 받는다."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    ctrl.seek_combined_ms(4000)   # 갭 (3000~5000) 진입 → _active_idx = -1
    player.load.reset_mock()
    ctrl.seek_combined_ms(6000)   # b 진입
    player.load.assert_called_once()
    assert player.load.call_args.kwargs.get("hold_last_frame") is False


def test_last_segment_end_triggers_pause():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"))
    ctrl.seek_combined_ms(0)
    ctrl.on_main_position_changed(3000)
    player.pause.assert_called_once()


def test_media_ended_advances_to_next_segment():
    """소스 파일 끝(EndOfMedia) 도달 시 다음 segment 로 진행 + 재생 재개.

    회귀(사용자 보고): 4개 클립 중 3번째가 자기 소스 파일의 끝에서 끝나면 Qt 가
    EndOfMedia 로 멈추는데, position_changed 가 seg_dur 에 도달 못 해 advance 가
    누락 → 4번째로 못 넘어가고 정지. EndOfMedia 를 별도 advance 경로로 받아 해결.
    """
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(1000)   # a 활성
    player.load.reset_mock()
    player.play.reset_mock()
    ctrl.on_media_ended()
    assert ctrl.active_segment_id == "b"
    player.load.assert_called_once()
    player.play.assert_called()   # EndOfMedia ⇒ 재생 중이었으므로 재개


def test_media_ended_on_last_segment_pauses():
    """마지막 segment 의 소스 끝이면 정지 (다음이 없음)."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"))
    ctrl.seek_combined_ms(0)
    player.pause.reset_mock()
    ctrl.on_media_ended()
    player.pause.assert_called()


def test_media_ended_after_position_advance_does_not_double_advance():
    """position 기반 advance 와 EndOfMedia 가 둘 다 와도 한 번만 — 뒤늦은 EndOfMedia 가
    이미 넘어간 다음 클립을 즉시 정지/재-advance 시키면 안 됨(중복 advance 회귀)."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(2999)
    ctrl.on_main_position_changed(3000)   # position 기반으로 b 로 advance
    assert ctrl.active_segment_id == "b"
    player.pause.reset_mock()
    ctrl.on_media_ended()                 # 뒤늦은 EndOfMedia
    assert ctrl.active_segment_id == "b"
    player.pause.assert_not_called()


def test_media_ended_advances_into_gap_and_runs_clock(qtbot):
    """소스 끝 직후가 갭이면 갭으로 진입하고 가상 시계가 진행(재생 중이었으므로).

    qtbot — _gap_timer.start()/isActive 가 event dispatcher 를 요구.
    """
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    ctrl.seek_combined_ms(1000)   # a 활성
    ctrl.on_media_ended()
    assert ctrl._in_gap is True
    assert ctrl._gap_timer.isActive() is True


def test_active_segment_changed_signal_through_gap():
    """a → 갭 → b. active_segment_changed 가 a, "", b 순으로 emit."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    received: list[str] = []
    ctrl.active_segment_changed.connect(lambda sid: received.append(sid))
    ctrl.seek_combined_ms(0)         # a
    ctrl.seek_combined_ms(4000)      # 갭
    ctrl.seek_combined_ms(6000)      # b
    assert received == ["a", "", "b"]


def test_set_sidecar_resets_active_when_segment_gone():
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 3000, 2000, "b"))
    ctrl.seek_combined_ms(3500)
    sc = Sidecar(source_path="x", source_hash="h",
                 video_track=[_seg("a.mp4", 0, 3000, "a")])
    ctrl.set_sidecar(sc)
    assert ctrl.active_segment_id is None or ctrl.active_segment_id == "a"


def test_gap_entry_calls_show_black_frame():
    """갭 진입 시 player.show_black_frame() 호출."""
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    ctrl.seek_combined_ms(4000)
    player.show_black_frame.assert_called_once()


def test_gap_paused_then_play_resumes_virtual_clock(qtbot):
    """갭 안에서 paused → play 누르면 가상 시계가 시작돼 다음 segment 로 진행.

    회귀 fix (advisor 발견): 갭 진입 시 paused 였으면 timer 가 안 켜지고,
    이후 player.play() 만으로는 _in_gap 가드가 on_main_position_changed 를 차단해
    영원히 갭에 갇혔던 버그.
    """
    from PySide6.QtCore import QObject
    # qtbot 이 event loop 보장 — QTimer.isActive 정확히 동작.
    ctrl, player = _ctrl(_seg("a.mp4", 0, 3000, "a"), _seg("b.mp4", 5000, 2000, "b"))
    qtbot.addWidget(QObject.__class__) if False else None  # 더미 — qtbot 활성화만 위함
    # 갭 진입 — 처음엔 paused.
    player.is_playing.return_value = False
    ctrl.seek_combined_ms(4000)
    assert ctrl._in_gap is True
    # 사용자가 ▶ 누름 → playing_changed(True).
    ctrl._on_player_playing_changed(True)
    assert ctrl._gap_timer.isActive() is True
    # ▌ pause 다시 → 정지.
    ctrl._on_player_playing_changed(False)
    assert ctrl._gap_timer.isActive() is False
