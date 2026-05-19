"""SpeedInspector — 폼 값 ↔ SpeedEffect 양방향, spinbox·콤보·체크·삭제 버튼."""
from __future__ import annotations

import pytest

from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.inspectors.speed_inspector import SpeedInspector


@pytest.fixture
def inspector(qtbot):
    w = SpeedInspector()
    qtbot.addWidget(w)
    return w


def _make_speed(rate=2.0, audio="auto", show_hud=True, in_ms=1000, out_ms=6000) -> SpeedEffect:
    return SpeedEffect(
        in_ms=in_ms, out_ms=out_ms, rate=rate, audio=audio, show_hud=show_hud,
    )


def test_load_effect_populates_spinbox_and_combo(inspector):
    """rate 2.0 → spinbox 값 2.0, audio 'auto' → '자동', show_hud True 체크.
    in/out spin 도 설정값 그대로 표시."""
    eff = _make_speed(rate=2.0, audio="auto", in_ms=1000, out_ms=6000)
    inspector.set_effect(eff)
    assert abs(inspector._rate_spin.value() - 2.0) < 1e-6
    assert inspector._audio_combo.currentText() == "자동"
    assert inspector._show_hud_check.isChecked() is True
    assert inspector._in_spin.value() == 1000
    assert inspector._out_spin.value() == 6000


def test_rate_spinbox_range_step_suffix(inspector):
    """rate spinbox 의 [0.1, 32.0] 범위 + step 0.25 + suffix ' ×'."""
    assert inspector._rate_spin.minimum() == 0.1
    assert inspector._rate_spin.maximum() == 32.0
    assert abs(inspector._rate_spin.singleStep() - 0.25) < 1e-6
    assert inspector._rate_spin.suffix() == " ×"


def test_audio_auto_maps_to_label(inspector):
    """audio='auto' / 'mute' / 'atempo' 가 각각 자동 / 음소거 / 음성도 같이 라벨로 표시."""
    inspector.set_effect(_make_speed(audio="auto"))
    assert inspector._audio_combo.currentText() == "자동"
    inspector.set_effect(_make_speed(audio="mute"))
    assert inspector._audio_combo.currentText() == "음소거"
    inspector.set_effect(_make_speed(audio="atempo"))
    assert inspector._audio_combo.currentText() == "음성도 같이 (atempo)"


def test_rate_spin_change_emits_effect_changed(inspector, qtbot):
    """rate spinbox 를 0.5 로 바꾸면 effect_changed(rate=0.5)."""
    eff = _make_speed(rate=2.0)
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._rate_spin.setValue(0.5)

    assert any(abs(e.rate - 0.5) < 1e-6 for e in received)
    assert all(e.id == eff.id for e in received)


def test_rate_spin_arbitrary_value(inspector, qtbot):
    """spinbox 는 직접 입력으로 임의 값 (1.75 등) 가능 — preset 콤보가 막던 회귀 해소."""
    eff = _make_speed(rate=2.0)
    inspector.set_effect(eff)
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector._rate_spin.setValue(1.75)
    assert any(abs(e.rate - 1.75) < 1e-6 for e in received)


def test_audio_combo_change_emits(inspector, qtbot):
    """audio 콤보 → '음소거' 선택 시 effect_changed(audio='mute')."""
    eff = _make_speed(audio="auto")
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._audio_combo.setCurrentText("음소거")

    assert any(e.audio == "mute" for e in received)


def test_show_hud_toggle_emits(inspector, qtbot):
    """show_hud 체크박스 토글 → effect_changed(show_hud=False)."""
    eff = _make_speed(show_hud=True)
    inspector.set_effect(eff)

    received: list = []
    inspector.effect_changed.connect(received.append)

    inspector._show_hud_check.setChecked(False)

    assert any(e.show_hud is False for e in received)


def test_delete_button_emits_effect_deleted(inspector, qtbot):
    """'이 배속 삭제' 버튼 → effect_deleted(effect.id) 발화."""
    eff = _make_speed()
    inspector.set_effect(eff)

    with qtbot.waitSignal(inspector.effect_deleted, timeout=1000) as blocker:
        inspector._delete_btn.click()
    assert blocker.args == [eff.id]


def test_set_effect_none_disables_form(inspector):
    """None 전달 시 폼 모든 위젯이 disabled."""
    inspector.set_effect(None)
    assert inspector._rate_spin.isEnabled() is False
    assert inspector._audio_combo.isEnabled() is False
    assert inspector._show_hud_check.isEnabled() is False
    assert inspector._delete_btn.isEnabled() is False


def test_load_effect_alias_works(inspector):
    """load_effect alias 도 set_effect 와 동일 동작."""
    eff = _make_speed(rate=1.5)
    inspector.load_effect(eff)
    assert abs(inspector._rate_spin.value() - 1.5) < 1e-6


def test_no_signal_during_set_effect_load(inspector, qtbot):
    """set_effect 로 폼 채우는 동안 effect_changed 가 발화하지 않음 (re-entrancy 방지)."""
    received: list = []
    inspector.effect_changed.connect(received.append)
    inspector.set_effect(_make_speed(rate=1.5, audio="atempo", show_hud=False))
    assert received == []
