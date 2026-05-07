"""VideoTab 편집 모드 통합."""
from pathlib import Path

import pytest

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    """간단한 가짜 mp4 — 실제 디코딩은 안 되지만 파일 존재로 충분."""
    p = tmp_path / "sample.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 100_000)
    return p


def test_video_tab_starts_with_edit_mode_off(qtbot, tmp_path: Path, sample_mp4: Path):
    tab = VideoTab(
        path=sample_mp4, source_label="sample",
        duration_ms=10_000,
        player_settings=PlayerSettings(),
        player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    assert tab.is_edit_mode_on() is False


def test_video_tab_toggle_edit_mode_emits_signal(qtbot, tmp_path: Path, sample_mp4: Path):
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    with qtbot.waitSignal(tab.edit_mode_toggled, timeout=1000) as blocker:
        tab.set_edit_mode(True)
    assert blocker.args == [True]
    assert tab.is_edit_mode_on() is True


def test_video_tab_loads_existing_sidecar(qtbot, tmp_path: Path, sample_mp4: Path):
    """이미 .kstudio 가 있으면 효과들이 로드돼야 한다."""
    from screen_recorder.effects import (
        SidecarStore, Sidecar, Trim, compute_video_hash,
    )
    sidecar_dir = tmp_path / "sidecars"
    store = SidecarStore(sidecar_dir)
    sc = Sidecar(
        source_path=str(sample_mp4),
        source_hash=compute_video_hash(sample_mp4),
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=1000, out_ms=4000, text="hi")],
    )
    store.save_for(sample_mp4, sc)

    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=sidecar_dir,
    )
    qtbot.addWidget(tab)
    assert len(tab.sidecar().effects) == 1
    assert tab.sidecar().effects[0].text == "hi"


def test_video_tab_creates_empty_sidecar_when_missing(qtbot, tmp_path: Path, sample_mp4: Path):
    """.kstudio 없으면 효과 0개로 시작."""
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    assert len(tab.sidecar().effects) == 0


def test_ctrl_e_toggles_edit_mode(qtbot, tmp_path: Path, sample_mp4: Path):
    from PySide6.QtCore import Qt

    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    assert tab.is_edit_mode_on() is False
    qtbot.keyClick(tab, Qt.Key_E, modifier=Qt.ControlModifier)
    assert tab.is_edit_mode_on() is True
    qtbot.keyClick(tab, Qt.Key_E, modifier=Qt.ControlModifier)
    assert tab.is_edit_mode_on() is False


def test_video_tab_lanes_visibility_follows_edit_mode(qtbot, tmp_path: Path, sample_mp4: Path):
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    assert tab.lanes_widget().isVisible() is False
    tab.set_edit_mode(True)
    assert tab.lanes_widget().isVisible() is True
    tab.set_edit_mode(False)
    assert tab.lanes_widget().isVisible() is False
