"""빈 영상 프로젝트 — 소스 영상 없이 시작해 클립을 조립하는 탭 (「새 영상 프로젝트」).

핵심 계약:
- 소스 파일이 없어도 탭이 열리고, 트랙은 비어 있다 (기본 segment 자동 생성 안 함).
- 저장은 프로젝트 .kstudio 파일 하나로 — 영상 hash 가 없으므로 그게 유일한 정체성.
- 클립을 넣으면 미리보기가 실제로 그 클립을 로드한다 (검은 화면에 머물지 않음).
"""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.ui.video.clip_clipboard import clipboard
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture(autouse=True)
def clean_clipboard():
    clipboard().clear()
    yield
    clipboard().clear()


@pytest.fixture(autouse=True)
def probed_duration(monkeypatch):
    """테스트용 가짜 mp4 는 ffprobe 가 길이를 못 읽는다 — 5초로 고정.

    길이 0 인 영상은 트랙에 넣지 않는 것이 정상 동작이라, 픽스처가 없으면 삽입 자체가
    거부돼 테스트 의도(빈 프로젝트 조립)를 검증하지 못한다.
    """
    import screen_recorder.services.media_probe as media_probe
    monkeypatch.setattr(media_probe, "probe_duration_ms", lambda _src: 5000)


def _mp4(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    return p


def _blank_tab(qtbot, tmp_path: Path, name: str = "새 영상 1") -> VideoTab:
    project = tmp_path / "sidecars" / f"{name}.kstudio"
    tab = VideoTab(
        path=project, source_label="new", duration_ms=0,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars", project_path=project,
    )
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    return tab


def test_blank_tab_opens_with_empty_track(qtbot, tmp_path):
    """소스 파일이 없어도 열리고, 자동 채움 없이 빈 트랙으로 시작한다."""
    tab = _blank_tab(qtbot, tmp_path)
    assert tab.is_blank_project() is True
    assert tab.sidecar().video_track == []
    # 소스 영상이 없다는 사실이 사이드카에 남는다 — export 가 "트랙이 권위" 를 판별하는 근거.
    assert tab.sidecar().source_path == ""


def test_blank_tab_does_not_load_missing_source(qtbot, tmp_path):
    """존재하지 않는 경로를 player 에 load 하지 않는다 (빈 트랙일 때)."""
    tab = _blank_tab(qtbot, tmp_path)
    loaded: list = []
    tab.player.load = lambda *a, **k: loaded.append(a)
    tab.show()
    qtbot.waitExposed(tab)
    assert loaded == []


def test_blank_tab_shows_hint_until_first_clip(qtbot, tmp_path):
    """빈 화면은 '고장' 으로 읽힌다 — 무엇을 해야 하는지 안내하고, 클립이 오면 사라진다."""
    tab = _blank_tab(qtbot, tmp_path)
    tab.show()
    qtbot.waitExposed(tab)
    assert tab.player._placeholder.isVisible()
    assert "Ctrl+V" in tab.player._placeholder.text()

    tab._on_track_insert_files([str(_mp4(tmp_path, "a.mp4"))], 0)
    assert not tab.player._placeholder.isVisible()


def test_first_clip_is_actually_loaded_into_player(qtbot, tmp_path, monkeypatch):
    """첫 클립이 들어오면 player 가 그 파일을 실제로 load 한다.

    회귀 방지: SegmentPlaybackController 가 '첫 segment 는 이미 로드됨' 으로 가정하면
    load 를 건너뛰어 미리보기가 검은 화면에 머문다.
    """
    import screen_recorder.services.media_probe as media_probe
    monkeypatch.setattr(media_probe, "probe_duration_ms", lambda _src: 5000)
    a_path = _mp4(tmp_path, "a.mp4")
    tab = _blank_tab(qtbot, tmp_path)
    tab.show()
    qtbot.waitExposed(tab)
    loaded: list[str] = []
    tab.player.load = lambda p, **k: loaded.append(str(p))

    tab._on_track_insert_files([str(a_path)], 0)

    assert len(tab.sidecar().video_track) == 1
    assert loaded and loaded[-1] == str(a_path)


def test_blank_project_autosaves_to_its_own_file(qtbot, tmp_path):
    """저장은 프로젝트 .kstudio 로 — 영상 hash 기반 파일명이 아니라."""
    from screen_recorder.effects.sidecar import load as load_sidecar

    tab = _blank_tab(qtbot, tmp_path)
    project = tmp_path / "sidecars" / "새 영상 1.kstudio"
    tab._on_track_insert_files([str(_mp4(tmp_path, "a.mp4"))], 0)
    assert tab._edit_controller.save_now() is True

    assert project.exists()
    saved = load_sidecar(project)
    assert len(saved.video_track) == 1
    assert saved.source_path == ""
    # 사이드카 폴더에 hash 기반 파일이 추가로 생기지 않았다.
    assert [p.name for p in project.parent.glob("*.kstudio")] == [project.name]


def test_blank_project_reloads_from_its_file(qtbot, tmp_path):
    """다시 열면(사이드카 명시 지정) 트랙이 그대로 돌아온다."""
    tab = _blank_tab(qtbot, tmp_path)
    a_path = _mp4(tmp_path, "a.mp4")
    tab._on_track_insert_files([str(a_path)], 0)
    tab._edit_controller.save_now()
    project = tmp_path / "sidecars" / "새 영상 1.kstudio"

    reopened = VideoTab(
        path=project, source_label="new", duration_ms=0,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars", project_path=project,
        sidecar_path=project,
    )
    qtbot.addWidget(reopened)
    assert len(reopened.sidecar().video_track) == 1
    assert reopened.sidecar().video_track[0].src == str(a_path)


def test_paste_clip_from_another_tab_into_blank_project(qtbot, tmp_path):
    """다른 영상 탭에서 자른 클립을 빈 프로젝트에 Ctrl+V — 이번 기능의 주 사용 흐름."""
    a_path = _mp4(tmp_path, "a.mp4")
    src_tab = VideoTab(
        path=a_path, source_label="a", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars_a",
    )
    qtbot.addWidget(src_tab)
    src_tab.set_edit_mode(True)
    src_tab.show()
    qtbot.waitExposed(src_tab)
    first_id = src_tab.sidecar().video_track[0].id
    src_tab._edit_controller.split_segment(first_id, at_local_ms=4000)
    src_tab._active_kind = "segment"
    src_tab._active_id = src_tab.sidecar().video_track[1].id
    src_tab.setFocus()
    qtbot.keyClick(src_tab, Qt.Key_C, Qt.ControlModifier)

    blank = _blank_tab(qtbot, tmp_path)
    blank.show()
    qtbot.waitExposed(blank)
    blank.setFocus()
    qtbot.keyClick(blank, Qt.Key_V, Qt.ControlModifier)

    track = blank.sidecar().video_track
    assert len(track) == 1
    assert track[0].src == str(a_path)
    assert track[0].start_ms == 0        # 인디케이터가 0 이고 트랙이 비었으니 0
    assert track[0].duration_ms == 6000


def test_effect_add_on_empty_blank_tab_is_a_no_op(qtbot, tmp_path):
    """길이가 0 인 빈 트랙에서 T(캡션 추가) 를 눌러도 죽지 않는다."""
    tab = _blank_tab(qtbot, tmp_path)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyClick(tab, Qt.Key_T)
    assert tab.sidecar().effects == []
