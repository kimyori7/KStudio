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


def test_ctrl_e_requests_edit_mode_toggle(qtbot, tmp_path: Path, sample_mp4: Path):
    """Ctrl+E 는 직접 토글하지 않고 edit_mode_change_requested(원하는 상태)를 emit —
    MainWindow 가 전역 라우팅으로 모든 탭에 적용한다(탭 단독으론 상태 불변이 계약)."""
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
    requested = []
    tab.edit_mode_change_requested.connect(requested.append)
    assert tab.is_edit_mode_on() is False
    qtbot.keyClick(tab, Qt.Key_E, modifier=Qt.ControlModifier)
    assert requested == [True]                    # OFF → ON 요청
    # MainWindow 라우팅 모사. (controls 버튼 동기화가 같은 상태 요청을 echo 하므로
    # — 실제 앱에선 재적용 no-op — Ctrl+E 계약만 보려고 리스트를 비운다.)
    tab.set_edit_mode(True)
    requested.clear()
    qtbot.keyClick(tab, Qt.Key_E, modifier=Qt.ControlModifier)
    assert requested == [False]                   # ON → OFF 요청


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


def test_video_tab_edit_off_caps_timeline_to_seekbar(qtbot, tmp_path: Path, sample_mp4: Path):
    """편집 모드 OFF 시 timeline 은 시크 바 한 줄 높이로만 제한되고 **항상 visible**.

    (구 Phase 31 은 OFF 시 timeline 을 통째로 hide 했으나, 시크 바까지 사라지는
    회귀라 2026-06-04 폐기 — _apply_timeline_layout 이 높이 cap 방식으로 대체.)
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
    # 편집 OFF — timeline 은 보이되(시크 바 공통) 높이가 시크 바 한 줄로 cap.
    assert tab.timeline.isVisible(), "편집 OFF 여도 시크 바(timeline)는 보여야 함"
    assert tab.timeline.maximumHeight() == tab.timeline.playback_height()
    # 편집 ON — 높이 제한 해제(트랙/효과 줄까지 펼침).
    tab.set_edit_mode(True)
    assert tab.timeline.isVisible()
    assert tab.timeline.maximumHeight() > tab.timeline.playback_height()
