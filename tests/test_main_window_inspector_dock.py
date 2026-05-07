"""MainWindow 의 인스펙터 도크 등록·가시성."""
import pytest

# MainWindow 풀-스택 테스트는 시간이 오래 걸리고 의존성 많음. 대신 InspectorPanel 도크
# 가 main_window 에 attach 됐는지만 확인하는 가벼운 테스트.


def test_main_window_has_inspector_dock(qtbot, qapp):
    from screen_recorder.app.main import build_main_window

    w = build_main_window()
    qtbot.addWidget(w)
    assert hasattr(w, "inspector_dock")
    assert hasattr(w, "inspector_panel")
    # 기본은 숨김
    assert w.inspector_dock.isVisible() is False or w.inspector_dock.isHidden() is True


def test_inspector_dock_appears_on_video_edit_mode(qtbot, qapp, tmp_path):
    """영상 탭이 편집 모드 ON 되면 인스펙터 도크 등장."""
    from screen_recorder.app.main import build_main_window
    from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
    from screen_recorder.ui.video_tab import VideoTab
    from screen_recorder.ui.mode_controller import AppMode

    sample = tmp_path / "v.mp4"
    sample.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 10_000)

    w = build_main_window()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)

    tab = VideoTab(
        path=sample, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    # _add_tab 은 tab_added 시그널을 발화 → _on_tab_added → _hookup_video_tab_inspector
    w.tab_area._add_tab(tab, AppMode.VIDEO, entry_id=1, label="v")

    tab.set_edit_mode(True)
    assert w.inspector_dock.isVisible()
    tab.set_edit_mode(False)
    assert w.inspector_dock.isVisible() is False
