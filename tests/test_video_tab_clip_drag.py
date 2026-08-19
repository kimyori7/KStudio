"""트랙에서 클립을 끌어 놓으면 좁은 빈칸에 끼워 넣고, 민 사실을 알린다 (VideoTab 배선).

lane 이 보내는 값과 EditController 의 배치는 각각 tests/test_video_track_lane.py,
tests/test_edit_controller_ripple_move.py 가 다룬다. 여기서는 그 둘을 잇는 VideoTab 의
핸들러 — 실제로 컨트롤러를 부르는지, 사용자에게 알리는지 — 를 본다.
"""
from pathlib import Path

import pytest

from screen_recorder.core.settings import PlayerHotkeys, PlayerSettings
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def tab(qtbot, tmp_path: Path) -> VideoTab:
    """트랙: 원본 [0,10000) — 빈칸 1초 — c2 [11000,20000) — x [40000,45000)"""
    src = tmp_path / "a.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    t = VideoTab(path=src, source_label="a", duration_ms=10_000,
                 player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
                 sidecar_dir=tmp_path / "sidecars")
    qtbot.addWidget(t)
    t.set_edit_mode(True)
    t._edit_controller.insert_segment(
        99, VideoSegment(src="c2.mp4", id="c2", src_duration_ms=9000, start_ms=11_000))
    t._edit_controller.insert_segment(
        99, VideoSegment(src="x.mp4", id="x", src_duration_ms=5000, start_ms=40_000))
    return t


def _starts(tab: VideoTab) -> dict:
    return {s.id: s.start_ms for s in tab.sidecar().video_track}


def test_drag_signal_inserts_into_narrow_gap(tab):
    """lane 이 보낸 위치로 클립이 빈칸에 들어가고 뒤 클립이 밀린다."""
    tab.timeline.video_track_lane.segment_position_changed.emit("x", 10_200)
    starts = _starts(tab)
    assert starts["x"] == 10_000
    assert starts["c2"] == 15_000, "1초 빈칸에 5초가 들어가 4초 밀림"


def test_drag_tells_the_user_that_clips_were_pushed(tab, monkeypatch):
    """지시하지 않은 클립이 움직였으므로 조용히 넘기지 않는다."""
    said = []
    monkeypatch.setattr(tab.player, "flash_action", said.append)
    tab.timeline.video_track_lane.segment_position_changed.emit("x", 10_200)
    assert said, "안내가 없다"
    assert "1개" in said[-1] and "4.0초" in said[-1]


def test_drag_to_empty_space_says_nothing(tab, monkeypatch):
    """넉넉한 자리로 옮기면 알릴 게 없다 — 안내로 도배하지 않는다."""
    said = []
    monkeypatch.setattr(tab.player, "flash_action", said.append)
    tab.timeline.video_track_lane.segment_position_changed.emit("x", 60_000)
    assert _starts(tab)["x"] == 60_000
    assert said == []
