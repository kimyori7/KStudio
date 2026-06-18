"""ArrowInspector — 폼 값 ↔ ArrowEffect 양방향."""
from __future__ import annotations

import pytest

from screen_recorder.effects.types.arrow import ArrowEffect, Point, Fade
from screen_recorder.ui.video.inspectors.arrow_inspector import ArrowInspector


@pytest.fixture
def inspector(qtbot):
    w = ArrowInspector()
    qtbot.addWidget(w)
    return w


def _make_arrow(**kw) -> ArrowEffect:
    return ArrowEffect(in_ms=kw.pop("in_ms", 1000), out_ms=kw.pop("out_ms", 4000), **kw)


def test_load_effect_populates_form(inspector):
    eff = _make_arrow(
        start=Point(x=0.1, y=0.2), end=Point(x=0.9, y=0.8),
        color="#abcdef", thickness=12,
        fade=Fade(in_ms=150, out_ms=250),
    )
    inspector.set_effect(eff)
    assert abs(inspector._start_x_spin.value() - 0.1) < 1e-6
    assert abs(inspector._end_y_spin.value() - 0.8) < 1e-6
    assert inspector._color == "#abcdef"
    assert inspector._thickness_spin.value() == 12
    assert inspector._fade_in_spin.value() == 150


def test_change_emits_effect_changed(inspector):
    eff = _make_arrow()
    inspector.set_effect(eff)
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector._thickness_spin.setValue(20)
    assert any(e.thickness == 20 for e in received)
    assert all(e.id == eff.id for e in received)


def test_start_x_change_emits_correct_point(inspector):
    eff = _make_arrow()
    inspector.set_effect(eff)
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector._start_x_spin.setValue(0.15)
    last = received[-1]
    assert abs(last.start.x - 0.15) < 1e-6
    # end 은 변경 없음 (기본값 그대로).
    assert abs(last.end.x - 0.7) < 1e-6


def test_delete_button_emits(inspector, qtbot):
    eff = _make_arrow()
    inspector.set_effect(eff)
    with qtbot.waitSignal(inspector.effect_deleted, timeout=1000) as blocker:
        inspector._delete_btn.click()
    assert blocker.args == [eff.id]


def test_set_effect_none_disables_form(inspector):
    inspector.set_effect(None)
    assert inspector._start_x_spin.isEnabled() is False
    assert inspector._thickness_spin.isEnabled() is False
    assert inspector._delete_btn.isEnabled() is False


def test_no_signal_during_set_effect(inspector):
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector.set_effect(_make_arrow(thickness=8))
    assert received == []


def test_head_scale_loads(inspector):
    inspector.set_effect(_make_arrow(head_scale=2.5))
    assert abs(inspector._head_scale_spin.value() - 2.5) < 1e-6


def test_head_scale_change_emits(inspector):
    inspector.set_effect(_make_arrow())
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector._head_scale_spin.setValue(3.0)
    assert any(abs(e.head_scale - 3.0) < 1e-6 for e in received)
