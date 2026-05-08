"""EffectLanesWidget — 어느 lane 우클릭이든 같은 6항목 통합 메뉴."""
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


def test_right_click_on_caption_lane_shows_menu(widget, qtbot):
    """캡션 lane 우클릭 → 6항목 메뉴 (캡션·자르기 한점·자르기 구간·배속·줌·곁들임)."""
    cap_lane = widget.lane_for_type("caption")
    assert cap_lane is not None

    # request_add_at 가 widget 의 _show_add_menu_at 를 호출 → popup (non-blocking)
    cap_lane.request_add_at.emit(3_000)
    menu = widget._last_menu
    assert menu is not None
    actions = menu.actions()
    labels = [a.text() for a in actions if not a.isSeparator()]
    assert any("캡션" in l for l in labels)
    assert any("자르기 (한 점)" in l for l in labels)
    assert any("자르기 (구간)" in l for l in labels)
    assert any("배속" in l for l in labels)
    assert any("줌" in l for l in labels)
    assert any("곁들임" in l for l in labels)
    menu.close()   # cleanup


def test_all_menu_items_enabled(widget, qtbot):
    """Stage 7 (2026-05-08) 부터 메뉴의 6개 항목이 모두 활성화.

    Stage 5: speed 활성화. Stage 6: zoom 활성화. Stage 7: broll 활성화.
    """
    cap_lane = widget.lane_for_type("caption")
    cap_lane.request_add_at.emit(3_000)
    menu = widget._last_menu
    assert menu is not None
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert all(a.isEnabled() for a in actions), \
        f"disabled actions: {[a.text() for a in actions if not a.isEnabled()]}"
    # 메뉴 항목이 정확히 6개 — 캡션 / 자르기(한점) / 자르기(구간) / 배속 / 줌 / 곁들임.
    assert len(actions) == 6
    menu.close()


def test_clicking_caption_emits_request_add(widget, qtbot):
    cap_lane = widget.lane_for_type("caption")
    cap_lane.request_add_at.emit(3_000)
    menu = widget._last_menu
    cap_action = next(a for a in menu.actions() if "캡션" in a.text())
    with qtbot.waitSignal(widget.request_add, timeout=500) as blocker:
        cap_action.trigger()
    assert blocker.args == ["caption", 3_000]
    menu.close()


def test_clicking_cut_splice_emits_request_add(widget, qtbot):
    cap_lane = widget.lane_for_type("caption")
    cap_lane.request_add_at.emit(2_500)
    menu = widget._last_menu
    splice_action = next(a for a in menu.actions() if "한 점" in a.text())
    with qtbot.waitSignal(widget.request_add, timeout=500) as blocker:
        splice_action.trigger()
    assert blocker.args == ["cut_splice", 2_500]
    menu.close()


def test_clicking_cut_range_emits_request_add(widget, qtbot):
    cap_lane = widget.lane_for_type("caption")
    cap_lane.request_add_at.emit(4_000)
    menu = widget._last_menu
    range_action = next(a for a in menu.actions() if "구간" in a.text())
    with qtbot.waitSignal(widget.request_add, timeout=500) as blocker:
        range_action.trigger()
    assert blocker.args == ["cut_range", 4_000]
    menu.close()


def test_right_click_on_speed_lane_shows_same_menu(widget, qtbot):
    """speed lane 우클릭이라도 메뉴는 동일 — 모든 type 항목 노출."""
    speed_lane = widget.lane_for_type("speed")
    assert speed_lane is not None
    speed_lane.request_add_at.emit(1_000)
    menu = widget._last_menu
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("캡션" in l for l in labels)
    assert any("자르기" in l for l in labels)
    menu.close()
