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


def test_video_tab_main_splitter_has_preview_and_timeline(qtbot, tmp_path: Path, sample_mp4: Path):
    """preview ↔ timeline 사이 QSplitter — 사용자가 핸들로 높이 조절."""
    from PySide6.QtWidgets import QSplitter
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    splitter = tab._main_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.count() == 2   # preview container + timeline
    assert splitter.childrenCollapsible() is False   # 한쪽 0px 로 접힘 보호.


def test_video_tab_splitter_preview_larger_initially(qtbot, tmp_path: Path, sample_mp4: Path):
    """초기 비중 — preview 영역이 timeline 보다 큼 (stretch 4:1)."""
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.resize(800, 600)
    tab.show()
    qtbot.waitExposed(tab)
    sizes = tab._main_splitter.sizes()
    assert len(sizes) == 2
    # preview (index 0) > timeline (index 1).
    assert sizes[0] > sizes[1]


def test_video_tab_does_not_accept_drops_preview_area(qtbot, tmp_path: Path, sample_mp4: Path):
    """회귀: 사용자가 외부 파일을 영상 미리보기 영역 위에 드롭해도 video_track 변경 X.

    2026-05-12 사고: 발표용 폴더 .mp4 를 미리보기 위로 드롭 → 의도치 않게 video_track
    끝에 append 되어 11:40 분량으로 늘어남. 가드: VideoTab 자체는 setAcceptDrops(False)
    — 드롭은 video_track_lane (영상 바) 위에서만 수락.
    """
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    # 가드: VideoTab 은 외부 드래그 거부.
    assert not tab.acceptDrops(), (
        "VideoTab 이 드롭을 수락하면 사용자가 미리보기 위에 의도치 않게 영상을 "
        "떨어뜨려 video_track 이 오염됨"
    )


def test_video_tab_edit_off_hides_timeline(qtbot, tmp_path: Path, sample_mp4: Path):
    """편집 모드 OFF 시 timeline widget 자체가 hidden (일반 플레이어 모습).

    Phase 31: setSizes([total, 0]) 대신 timeline.setVisible(off) — splitter 가
    hidden 자식을 자동으로 거둬들이고, 사용자가 드래그한 비율은 보존.
    """
    tab = VideoTab(
        path=sample_mp4, source_label="sample", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.resize(800, 600)
    tab.show()
    qtbot.waitExposed(tab)
    # 편집 OFF — timeline widget hidden.
    assert not tab.timeline.isVisible(), "편집 OFF 인데 timeline 이 visible"
    # 편집 ON — timeline visible.
    tab.set_edit_mode(True)
    assert tab.timeline.isVisible(), "편집 ON 인데 timeline hidden"
