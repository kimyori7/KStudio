"""SegmentPlaybackController — 단일 player + segment 순차 재생."""
from unittest.mock import MagicMock

from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.segment_playback import SegmentPlaybackController


def _seg(src: str, dur: int, sid: str) -> VideoSegment:
    return VideoSegment(
        id=sid, src=src, src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
    )


def _ctrl(*segments: VideoSegment) -> tuple[SegmentPlaybackController, MagicMock]:
    player = MagicMock()
    ctrl = SegmentPlaybackController(player)
    sc = Sidecar(source_path="x", source_hash="h", video_track=list(segments))
    ctrl.set_sidecar(sc)
    return ctrl, player


def test_combined_duration_is_sum_of_segments():
    ctrl, _ = _ctrl(_seg("a", 3000, "a"), _seg("b", 2000, "b"))
    assert ctrl.combined_duration_ms() == 5000


def test_seek_combined_routes_to_first_segment():
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(1000)
    # a.mp4 로 load, src_in_ms=0 + 1000 = 1000 시크.
    player.load.assert_called_once()
    player.seek_ms.assert_called_with(1000)
    assert ctrl.active_segment_id == "a"


def test_seek_combined_routes_to_second_segment():
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(4000)
    # b.mp4, local=1000.
    player.seek_ms.assert_called_with(1000)
    assert ctrl.active_segment_id == "b"


def test_position_change_emits_combined_ms(qtbot):
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(0)   # a 활성화.
    received = []
    ctrl.combined_position_changed.connect(lambda v: received.append(v))
    ctrl.on_main_position_changed(1500)
    assert received[-1] == 1500


def test_position_change_in_second_segment_emits_offset_combined(qtbot):
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(3500)   # b 활성화 + local 500.
    received = []
    ctrl.combined_position_changed.connect(lambda v: received.append(v))
    ctrl.on_main_position_changed(800)
    # b src_in=0 → local=800. combined = 3000 (a) + 800 = 3800.
    assert received[-1] == 3800


def test_segment_boundary_auto_advances():
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(2999)
    # 활성: a. 그리고 a 의 끝 (3000) 도달.
    player.load.reset_mock()
    player.seek_ms.reset_mock()
    ctrl.on_main_position_changed(3000)
    # b 로 자동 전환 — load(b), seek_ms(0).
    assert ctrl.active_segment_id == "b"
    player.load.assert_called_once()
    player.seek_ms.assert_called_with(0)


def test_last_segment_end_triggers_pause():
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"))
    ctrl.seek_combined_ms(0)
    ctrl.on_main_position_changed(3000)
    player.pause.assert_called_once()


def test_active_segment_changed_signal(qtbot):
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    received = []
    ctrl.active_segment_changed.connect(lambda sid: received.append(sid))
    ctrl.seek_combined_ms(0)
    ctrl.seek_combined_ms(3500)
    assert received == ["a", "b"]


def test_set_sidecar_resets_active_when_segment_gone():
    ctrl, player = _ctrl(_seg("a.mp4", 3000, "a"), _seg("b.mp4", 2000, "b"))
    ctrl.seek_combined_ms(3500)   # b 활성.
    # b 를 제거.
    sc = Sidecar(source_path="x", source_hash="h",
                 video_track=[_seg("a.mp4", 3000, "a")])
    ctrl.set_sidecar(sc)
    # active_idx 가 1 인데 list 길이가 1 → reset.
    assert ctrl.active_segment_id is None or ctrl.active_segment_id == "a"
