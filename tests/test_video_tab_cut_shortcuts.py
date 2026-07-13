"""VideoTab 자르기 단축키 — S (현재 위치에서 트랙 segment split).

구 C / Shift+C (CutEffect 추가) 단축키는 새 트랙 모델(Stage D)에서 제거됨 —
자르기는 트랙 lane 우클릭 메뉴 또는 단축키 S. 이 파일은 2026-07-13 그 현행
계약으로 재작성(과거 C/Shift+C 테스트는 잔재라 삭제).
"""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def tab(qtbot, tmp_path):
    # PlayerWidget 의 영상 로드 없이 단축키만 테스트.
    fake_video = tmp_path / "a.mp4"
    fake_video.write_bytes(b"\x00" * 4096)
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    t = VideoTab(
        path=fake_video,
        source_label="a.mp4",
        duration_ms=10000,
        player_settings=PlayerSettings(),
        player_hotkeys=PlayerHotkeys(),
        sidecar_dir=sidecar_dir,
    )
    qtbot.addWidget(t)
    t.set_edit_mode(True)
    # 위치 = 5000ms
    t.timeline.set_duration_ms(10000)
    t.timeline.set_position_ms(5000)
    return t


def test_S_splits_segment_at_current_position(tab, qtbot):
    tab.setFocus()
    assert len(tab.sidecar().video_track) == 1          # 기본 segment 1개
    qtbot.keyClick(tab, Qt.Key_S, Qt.NoModifier)
    segs = tab.sidecar().video_track
    assert len(segs) == 2                               # 5000ms 에서 둘로
    assert segs[1].start_ms == 5000


def test_S_inactive_when_edit_mode_off(tab, qtbot):
    tab.set_edit_mode(False)
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_S, Qt.NoModifier)
    assert len(tab.sidecar().video_track) == 1          # split 안 됨
