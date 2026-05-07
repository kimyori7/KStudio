"""MainWindow 의 인스펙터 도크 등록·가시성."""
import pytest

# MainWindow 풀-스택 테스트는 시간이 오래 걸리고 의존성 많음. 대신 InspectorPanel 도크
# 가 main_window 에 attach 됐는지만 확인하는 가벼운 테스트.

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_video_tab(tmp_path, name="v"):
    from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
    from screen_recorder.ui.video_tab import VideoTab

    sample = tmp_path / f"{name}.mp4"
    sample.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 10_000)
    return VideoTab(
        path=sample, source_label=name, duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )


def test_main_window_has_inspector_dock(qtbot, qapp):  # noqa: D103
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


def test_inspector_effect_changed_only_touches_active_tab(qtbot, qapp, tmp_path):
    """회귀: inspector_panel.effect_changed 는 현재 활성 탭에만 update_sidecar 를 보내야 한다.

    버그 재현 시나리오 (Stage 2 도입, Stage 3a 최초 노출):
    탭 N 개를 열면 _hookup_video_tab_inspector 가 N 개의 람다를 inspector_panel.effect_changed
    에 연결해 비활성 탭의 히스토리/사이드카도 오염시켰다.
    수정 후: 단일 라우팅 슬롯(_on_inspector_effect_changed)이 currentWidget() 만 확인.
    """
    import dataclasses
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.mode_controller import AppMode
    from screen_recorder.effects.types.caption import CaptionEffect

    w = build_main_window()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)

    # 두 탭 열기
    (tmp_path / "t1").mkdir()
    (tmp_path / "t2").mkdir()
    tab1 = _make_video_tab(tmp_path / "t1", "a")
    tab2 = _make_video_tab(tmp_path / "t2", "b")
    qtbot.addWidget(tab1)
    qtbot.addWidget(tab2)
    w.tab_area._add_tab(tab1, AppMode.VIDEO, entry_id=10, label="a")
    w.tab_area._add_tab(tab2, AppMode.VIDEO, entry_id=11, label="b")

    # tab1 에 캡션 효과 추가 (직접 edit_controller 통해서 — inspector 없이)
    cap = CaptionEffect(in_ms=0, out_ms=3000, text="Hello")
    tab1.edit_controller().add_effect(cap)
    # 이 시점 tab1 history: 1 push (initial + 1 add → can_undo=True)
    assert tab1.edit_controller()._history.can_undo(), "tab1 에 효과 추가 후 undo 가능해야 함"

    # tab2 는 깨끗한 상태
    assert not tab2.edit_controller()._history.can_undo(), "tab2 는 아직 수정 없음"

    # tab2 를 활성 탭으로 전환
    idx2 = w.tab_area.find_index_by_entry(11)
    w.tab_area.setCurrentIndex(idx2)

    # tab1 의 캡션을 수정한 것처럼 effect_changed 발화
    # (실제 인스펙터에서 폼 수정 시 emit 하는 것을 직접 시뮬레이션)
    modified = dataclasses.replace(cap, text="Modified")
    w.inspector_panel.effect_changed.emit(modified)

    # 수정 전 history 상태:
    #   tab1: can_undo=True (add_effect 1회)
    #   tab2: can_undo=False (clean)
    #
    # 버그 재현 시: tab1 도 update_sidecar 를 한 번 더 받아 can_undo 가 계속 True 이고
    #             tab2 도 update_sidecar 를 받아 can_undo=True 가 된다.
    # 수정 후 기대:
    #   tab1 history: 여전히 can_undo=True (이미 1 push 가 있음), *추가 push 없어야 함*
    #   tab2 history: effect id 가 없으므로 _patch_sidecar_effect 는 변화 없는 deepcopy
    #                 를 반환해 update_sidecar 가 호출되지만, 이건 활성 탭이라 허용.
    #
    # 핵심 검증: tab1 에 *추가 push* 가 발생하지 않아야 한다.
    # tab1.history undo 스택 크기를 저장해두고 비교한다.
    undo_depth_tab1_before = len(tab1.edit_controller()._history._undo)
    w.inspector_panel.effect_changed.emit(modified)  # 두 번째 emit (중복 push 체크)
    undo_depth_tab1_after = len(tab1.edit_controller()._history._undo)

    assert undo_depth_tab1_after == undo_depth_tab1_before, (
        f"tab1 의 undo 스택이 늘었다 ({undo_depth_tab1_before} → {undo_depth_tab1_after}): "
        "비활성 탭에 잘못된 update_sidecar 가 전달됐을 가능성이 있다."
    )
