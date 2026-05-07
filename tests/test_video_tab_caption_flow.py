"""VideoTab — 캡션 추가/수정/삭제 흐름."""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    return p


def _make_tab(qtbot, sample_mp4, tmp_path):
    tab = VideoTab(
        path=sample_mp4, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    return tab


def test_lane_request_add_creates_caption_at_ms(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    # 가짜로 lanes_widget 의 시그널 발화
    tab.lanes_widget().request_add.emit("caption", 5000)

    sc = tab.sidecar()
    assert len(sc.effects) == 1
    e = sc.effects[0]
    assert e.type == "caption"
    assert e.in_ms == 5000
    assert e.out_ms == 5000 + 3000


def test_t_shortcut_adds_caption_at_current_position(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    # 현재 재생 위치를 명시적으로 설정 — player_widget 의 mock
    tab._lanes_widget.set_position_ms(2000)
    qtbot.keyClick(tab, Qt.Key_T)

    sc = tab.sidecar()
    assert len(sc.effects) == 1
    assert sc.effects[0].in_ms == 2000
    assert sc.effects[0].out_ms == 5000


def test_t_shortcut_no_op_when_edit_mode_off(qtbot, sample_mp4, tmp_path):
    tab = VideoTab(
        path=sample_mp4, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    # 편집 모드 OFF
    qtbot.keyClick(tab, Qt.Key_T)
    assert len(tab.sidecar().effects) == 0


def test_lane_effect_deleted_removes_from_sidecar(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    cap_id = tab.sidecar().effects[0].id

    tab.lanes_widget().effect_deleted.emit(cap_id)
    assert tab.sidecar().effects == []


def test_lane_effect_changed_updates_sidecar(qtbot, sample_mp4, tmp_path):
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 1000)
    eff = tab.sidecar().effects[0]
    from dataclasses import replace
    moved = replace(eff, in_ms=2000, out_ms=2000 + 3000)

    tab.lanes_widget().effect_changed.emit(moved)
    assert tab.sidecar().effects[0].in_ms == 2000


def test_add_caption_near_end_clamps_or_rejects(qtbot, sample_mp4, tmp_path):
    """영상 9.5초 위치에 추가 시 기본 3초 길이가 안 들어가 → 거부 또는 clamp."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    tab.lanes_widget().request_add.emit("caption", 9500)
    sc = tab.sidecar()
    if len(sc.effects) == 1:
        # clamp 정책: 영상 끝까지 길이 자름
        e = sc.effects[0]
        assert e.in_ms == 9500
        assert e.out_ms <= 10_000
    else:
        # reject 정책: 0 개
        assert len(sc.effects) == 0
