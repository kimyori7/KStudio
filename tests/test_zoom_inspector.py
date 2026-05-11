"""ZoomInspector — 폼 값 ↔ ZoomEffect 양방향, cx/cy/scale/ease 정적 줌 편집."""
from __future__ import annotations

import pytest

from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint
from screen_recorder.ui.video.inspectors.zoom_inspector import ZoomInspector


@pytest.fixture
def inspector(qtbot):
    w = ZoomInspector()
    qtbot.addWidget(w)
    return w


def _make_zoom(cx=0.5, cy=0.5, scale=2.0, ease="in-out",
                in_ms=1000, out_ms=4000,
                in_anim_ms=300, out_anim_ms=300) -> ZoomEffect:
    pt = ZoomPoint(cx=cx, cy=cy, scale=scale)
    return ZoomEffect(
        in_ms=in_ms, out_ms=out_ms, start=pt, end=pt, ease=ease,
        in_anim_ms=in_anim_ms, out_anim_ms=out_anim_ms,
    )


def test_load_effect_populates_fields(inspector):
    """ZoomEffect(start.scale=2.5, cx=0.3, cy=0.4) → 폼에 그대로 표시."""
    eff = _make_zoom(cx=0.3, cy=0.4, scale=2.5, ease="linear")
    inspector.set_effect(eff)
    assert abs(inspector._cx_spin.value() - 0.3) < 1e-6
    assert abs(inspector._cy_spin.value() - 0.4) < 1e-6
    assert abs(inspector._scale_spin.value() - 2.5) < 1e-6
    assert inspector._ease_combo.currentText() == "선형"
    assert inspector._in_spin.value() == 1000
    assert inspector._out_spin.value() == 4000


def test_scale_change_emits_effect_changed_with_both_start_end(inspector):
    """scale spin 변경 → effect_changed 발화 시 start.scale == end.scale == 새 값."""
    eff = _make_zoom(scale=2.0)
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._scale_spin.setValue(3.0)

    assert len(received) >= 1
    last = received[-1]
    assert abs(last.start.scale - 3.0) < 1e-6
    assert abs(last.end.scale - 3.0) < 1e-6
    assert last.id == eff.id


def test_cx_cy_change_emits_with_both_start_end(inspector):
    """cx/cy 변경도 마찬가지 — start 와 end 양쪽 동시 반영.

    Phase 19.5: scale=2 에서 cx 의 valid range 는 [0.25, 0.75] — 0.3 으로 변경 시
    그 범위 안이라 그대로 emit.
    """
    eff = _make_zoom(cx=0.5, cy=0.5)   # scale=2 기본
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._cx_spin.setValue(0.3)

    assert any(abs(e.start.cx - 0.3) < 1e-6 and abs(e.end.cx - 0.3) < 1e-6
               for e in received)


def test_cx_clamped_to_valid_range_for_scale(inspector):
    """Phase 19.5: scale=2 일 때 cx 의 spin range 가 [0.25, 0.75] 로 잠겨, 그 밖 값 입력 시 clamp.

    사용자 보고: "가장자리에서 더 가는 느낌" — clamp 가 인스펙터에서도 같이 작동해야 함.
    """
    eff = _make_zoom(cx=0.5, cy=0.5, scale=2.0)
    inspector.set_effect(eff)
    # scale=2 → half=0.25, valid cx ∈ [0.25, 0.75]
    assert abs(inspector._cx_spin.minimum() - 0.25) < 0.01
    assert abs(inspector._cx_spin.maximum() - 0.75) < 0.01


def test_cx_range_widens_when_scale_lowered(inspector):
    """scale 을 낮추면 cx range 도 같이 넓어진다 (4× → 2×).

    tolerance 는 QDoubleSpinBox decimals=2 표현 정밀도(0.01) 만큼 — 0.125 가 0.13 으로
    rounding 될 수 있음.
    """
    inspector.set_effect(_make_zoom(cx=0.5, cy=0.5, scale=4.0))
    # 4× → half=0.125 → spin minimum ≈ 0.13 (decimals=2 round).
    assert abs(inspector._cx_spin.minimum() - 0.125) < 0.02
    inspector._scale_spin.setValue(2.0)
    # 2× → range=[0.25, 0.75]
    assert abs(inspector._cx_spin.minimum() - 0.25) < 0.02


def test_ease_combo_change_emits(inspector):
    """ease 콤보 → '선형' 선택 시 effect_changed(ease='linear')."""
    eff = _make_zoom(ease="in-out")
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._ease_combo.setCurrentText("선형")

    assert any(e.ease == "linear" for e in received)


def test_ease_value_to_label_mapping(inspector):
    """ease='in-out' / 'linear' / 'in' / 'out' 가 각각 라벨로 표시."""
    inspector.set_effect(_make_zoom(ease="in-out"))
    assert inspector._ease_combo.currentText() == "이즈 인/아웃"
    inspector.set_effect(_make_zoom(ease="linear"))
    assert inspector._ease_combo.currentText() == "선형"
    inspector.set_effect(_make_zoom(ease="in"))
    assert inspector._ease_combo.currentText() == "이즈 인"
    inspector.set_effect(_make_zoom(ease="out"))
    assert inspector._ease_combo.currentText() == "이즈 아웃"


def test_delete_emits_effect_deleted(inspector, qtbot):
    """'이 줌 삭제' 버튼 → effect_deleted(effect.id) 발화."""
    eff = _make_zoom()
    inspector.set_effect(eff)

    with qtbot.waitSignal(inspector.effect_deleted, timeout=1000) as blocker:
        inspector._delete_btn.click()
    assert blocker.args == [eff.id]


def test_set_effect_none_disables_form(inspector):
    """None 전달 시 폼 모든 위젯이 disabled."""
    inspector.set_effect(None)
    assert inspector._cx_spin.isEnabled() is False
    assert inspector._cy_spin.isEnabled() is False
    assert inspector._scale_spin.isEnabled() is False
    assert inspector._ease_combo.isEnabled() is False
    assert inspector._delete_btn.isEnabled() is False


def test_load_effect_alias_works(inspector):
    """load_effect alias 도 set_effect 와 동일 동작."""
    eff = _make_zoom(scale=1.5)
    inspector.load_effect(eff)
    assert abs(inspector._scale_spin.value() - 1.5) < 1e-6


def test_no_signal_during_set_effect_load(inspector):
    """set_effect 로 폼 채우는 동안 effect_changed 가 발화하지 않음 (re-entrancy 방지)."""
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector.set_effect(_make_zoom(cx=0.3, cy=0.4, scale=2.5, ease="linear"))
    assert received == []
