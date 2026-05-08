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
    """캡션 lane 우클릭 → 4항목 메뉴 (캡션·배속·줌·곁들임). 자르기는 트랙 lane 으로 이동."""
    cap_lane = widget.lane_for_type("caption")
    assert cap_lane is not None

    cap_lane.request_add_at.emit(3_000)
    menu = widget._last_menu
    assert menu is not None
    actions = menu.actions()
    labels = [a.text() for a in actions if not a.isSeparator()]
    assert any("캡션" in l for l in labels)
    assert any("배속" in l for l in labels)
    assert any("줌" in l for l in labels)
    assert any("곁들임" in l for l in labels)
    # 자르기 항목은 더 이상 없음.
    assert not any("자르기" in l for l in labels)
    menu.close()


def test_all_menu_items_enabled(widget, qtbot):
    """Stage D 부터 메뉴는 4개 항목 — 자르기는 트랙 lane 으로 이동."""
    cap_lane = widget.lane_for_type("caption")
    cap_lane.request_add_at.emit(3_000)
    menu = widget._last_menu
    assert menu is not None
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert all(a.isEnabled() for a in actions), \
        f"disabled actions: {[a.text() for a in actions if not a.isEnabled()]}"
    assert len(actions) == 4
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


def test_right_click_on_speed_lane_shows_same_menu(widget, qtbot):
    """speed lane 우클릭이라도 메뉴는 동일 — 4개 항목."""
    speed_lane = widget.lane_for_type("speed")
    assert speed_lane is not None
    speed_lane.request_add_at.emit(1_000)
    menu = widget._last_menu
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("캡션" in l for l in labels)
    assert any("배속" in l for l in labels)
    menu.close()
