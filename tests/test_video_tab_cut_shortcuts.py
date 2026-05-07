"""VideoTab 단축키 — C (splice) / Shift+C (구간) 가 CutEffect 추가."""
import os
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def tab(qtbot, tmp_path):
    # PlayerWidget 의 영상 로드 없이 단축키만 테스트.
    fake_video = tmp_path / "a.mp4"
    fake_video.write_bytes(b"\x00" * 4096)  # 1MB sha-1 폴백을 위해 일정 크기
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
    t._lanes_widget.set_duration_ms(10000)
    t._lanes_widget.set_position_ms(5000)
    return t


def test_C_adds_splice_at_current_position(tab, qtbot):
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_C, Qt.NoModifier)
    cuts = [e for e in tab._edit_controller.sidecar().effects if e.type == "cut"]
    assert len(cuts) == 1
    assert cuts[0].is_splice
    assert cuts[0].in_ms == 5000


def test_shift_C_adds_range_centered(tab, qtbot):
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_C, Qt.ShiftModifier)
    cuts = [e for e in tab._edit_controller.sidecar().effects if e.type == "cut"]
    assert len(cuts) == 1
    e = cuts[0]
    assert not e.is_splice
    assert e.in_ms == 4500
    assert e.out_ms == 5500
    assert not e.has_insert


def test_shortcuts_inactive_when_edit_mode_off(tab, qtbot):
    tab.set_edit_mode(False)
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_C, Qt.NoModifier)
    qtbot.keyClick(tab, Qt.Key_C, Qt.ShiftModifier)
    cuts = [e for e in tab._edit_controller.sidecar().effects if e.type == "cut"]
    assert len(cuts) == 0
