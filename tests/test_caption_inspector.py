"""CaptionInspector 폼."""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.effects.types.caption import (
    CaptionEffect, Font, Stroke, Background, Position, Fade,
)
from screen_recorder.ui.video.inspectors.caption_inspector import CaptionInspector


def _make_caption(text="hi") -> CaptionEffect:
    return CaptionEffect(in_ms=1000, out_ms=4000, text=text)


def test_inspector_loads_effect_into_widgets(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    eff = _make_caption("안녕")
    insp.set_effect(eff)
    assert insp.text_edit.toPlainText() == "안녕"
    assert insp.font_size.value() == 36   # 기본
    assert insp.bold_check.isChecked() is False


def test_text_change_emits_new_effect(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    eff = _make_caption("a")
    insp.set_effect(eff)

    received: list = []
    insp.effect_changed.connect(received.append)
    insp.text_edit.setPlainText("b")

    # 디바운스 또는 즉시 발화 — 마지막 효과의 text 가 'b'
    assert any(e.text == "b" for e in received)
    assert all(e.id == eff.id for e in received)   # id 보존


def test_font_size_change_emits(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(_make_caption())

    received: list = []
    insp.effect_changed.connect(received.append)
    insp.font_size.setValue(48)

    assert any(e.font.size == 48 for e in received)


def test_bold_toggle_emits(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(_make_caption())

    received: list = []
    insp.effect_changed.connect(received.append)
    insp.bold_check.setChecked(True)

    assert any(e.font.bold is True for e in received)


def test_stroke_toggle_creates_stroke(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(_make_caption())   # stroke=None

    received: list = []
    insp.effect_changed.connect(received.append)
    insp.stroke_check.setChecked(True)
    last = received[-1]
    assert last.stroke is not None


def test_anchor_change_emits(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(_make_caption())

    received: list = []
    insp.effect_changed.connect(received.append)
    # top-left 라디오 클릭
    insp.anchor_buttons["top-left"].setChecked(True)

    last = received[-1]
    assert last.position.anchor == "top-left"


def test_fade_change_emits(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(_make_caption())

    received: list = []
    insp.effect_changed.connect(received.append)
    insp.fade_in_spin.setValue(500)

    assert any(e.fade.in_ms == 500 for e in received)


def test_set_effect_none_disables_form(qtbot):
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    insp.set_effect(None)
    assert insp.text_edit.isEnabled() is False
