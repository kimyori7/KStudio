"""EffectLanesWidget — + 효과 추가 버튼 메뉴.

Phase 24 부터 lane 영구 표시 폐기 — "+" 버튼 또는 lane 우클릭으로 같은 5항목 메뉴.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMenu

from screen_recorder.effects import Sidecar
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


@pytest.fixture
def widget(qtbot):
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    w.set_duration_ms(10_000)
    w.set_sidecar(Sidecar())
    w.show()
    qtbot.waitExposed(w)
    return w


def _open_menu(widget) -> QMenu:
    widget._show_add_menu_at(3_000)
    menu = widget._last_menu
    assert menu is not None
    return menu


def test_plus_button_shows_5_items_menu(widget, qtbot):
    """+ 효과 추가 → 5항목 메뉴 (캡션·배속·줌·곁들임·화살표)."""
    menu = _open_menu(widget)
    actions = menu.actions()
    labels = [a.text() for a in actions if not a.isSeparator()]
    assert any("캡션" in l for l in labels)
    assert any("배속" in l for l in labels)
    assert any("줌" in l for l in labels)
    assert any("곁들임" in l for l in labels)
    assert any("화살표" in l for l in labels)
    assert not any("자르기" in l for l in labels)
    menu.close()


def test_all_menu_items_enabled(widget, qtbot):
    """메뉴는 6개 항목 — 캡션·배속·줌·곁들임·화살표·사각형 (2026-06-17 사각형 추가)."""
    menu = _open_menu(widget)
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert all(a.isEnabled() for a in actions), \
        f"disabled actions: {[a.text() for a in actions if not a.isEnabled()]}"
    assert len(actions) == 6
    assert any("사각형" in a.text() for a in actions)
    menu.close()


def test_clicking_caption_adds_empty_lane(widget, qtbot):
    """Phase 28 — 복수-라인 type (캡션) 클릭 시 빈 lane 한 줄 추가 (request_add 발화 X)."""
    menu = _open_menu(widget)
    cap_action = next(a for a in menu.actions() if "캡션" in a.text())
    assert widget._extra_empty_lanes.get("caption", 0) == 0
    with qtbot.assertNotEmitted(widget.request_add):
        cap_action.trigger()
    assert widget._extra_empty_lanes.get("caption", 0) == 1
    assert "caption" in widget._lanes
    menu.close()


def test_clicking_speed_emits_request_add(widget, qtbot):
    """단일-라인 type (배속) 클릭은 기존 request_add 흐름 — 효과 즉시 생성."""
    menu = _open_menu(widget)
    speed_action = next(a for a in menu.actions() if "배속" in a.text())
    with qtbot.waitSignal(widget.request_add, timeout=500) as blocker:
        speed_action.trigger()
    assert blocker.args == ["speed", 3_000, 0]
    menu.close()


def test_add_button_emits_at_playhead(widget, qtbot):
    """+ 효과 추가 버튼 — 단일-라인 type (배속) 은 현재 재생 위치 ms 로 emit."""
    widget.set_position_ms(4_500)
    widget._on_add_button_clicked()
    menu = widget._last_menu
    speed_action = next(a for a in menu.actions() if "배속" in a.text())
    with qtbot.waitSignal(widget.request_add, timeout=500) as blocker:
        speed_action.trigger()
    assert blocker.args == ["speed", 4_500, 0]
    menu.close()


def test_remove_lane_after_effect_deleted(widget, qtbot):
    """회귀 (2026-06-22): 줌 효과 추가 → Del 로 삭제 → '줌 라인 지우기' →
    빈 줌 lane 이 실제로 제거돼야 한다.

    Del 로 효과를 지우면 정책상 lane 은 (효과 0 이어도) 유지된다. 그 상태에서
    '이 라인 지우기' 를 누르면 효과·빈 row 모두 0 이라 두 분기를 모두 건너뛰고
    fall-through 해서 lane 이 안 사라지던 버그.
    """
    from screen_recorder.effects import Sidecar
    from screen_recorder.effects.types.zoom import ZoomEffect

    # 1) 줌 효과 1개 → 줌 lane 생성.
    sc_with = Sidecar(source_path="x", source_hash="h",
                      effects=[ZoomEffect(in_ms=1_000, out_ms=4_000)])
    widget.set_sidecar(sc_with)
    assert "zoom" in widget._lanes

    # 2) Del 로 효과 삭제 → 효과 0 인 사이드카 도착 (같은 영상이라 lane 유지).
    sc_empty = Sidecar(source_path="x", source_hash="h", effects=[])
    widget.set_sidecar(sc_empty)
    assert "zoom" in widget._lanes, "정책: 효과 0 이어도 lane 유지"
    assert widget._lanes["zoom"].effects() == []
    assert widget._extra_empty_lanes.get("zoom", 0) == 0

    # 3) '줌 라인 지우기' → lane 이 실제로 제거돼야 한다.
    widget._on_remove_lane_requested("zoom", 0)
    assert "zoom" not in widget._lanes
