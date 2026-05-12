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


def test_set_effect_with_same_text_does_not_reset_cursor(qtbot):
    """동일 text 로 set_effect 재호출 시 setPlainText 가 호출되지 않아 커서가
    리셋되지 않는다.

    회귀: refresh_from_sidecar 가 매 사이드카 갱신마다 set_effect 호출 →
    setPlainText 가 cursor pos 를 0 으로 리셋 → 사용자가 IME 로 타이핑 중이면
    다음 글자가 시작 위치에 끼어들어가 "확대" → "대확" 식으로 순서 뒤집힘.

    원인: textChanged 매 발화마다 _on_any_change → emit effect_changed → 외부에서
    sidecar 갱신 → refresh_from_sidecar 가 같은 텍스트로 set_effect 재호출.
    fix 는 set_effect 안에서 현재 텍스트와 동일하면 setPlainText skip.
    """
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    eff = _make_caption("확")
    insp.set_effect(eff)

    # 커서를 끝으로 이동 (사용자가 IME 로 다음 글자 입력 직전 상태 시뮬레이션).
    from PySide6.QtGui import QTextCursor
    cursor = insp.text_edit.textCursor()
    cursor.movePosition(QTextCursor.End)
    insp.text_edit.setTextCursor(cursor)
    end_pos = insp.text_edit.textCursor().position()
    assert end_pos == 1

    # 동일 text 로 set_effect 재호출 (refresh_from_sidecar 경로 모사).
    insp.set_effect(eff)
    # 커서가 끝(1)에 유지되어야 함 — 0 으로 리셋되면 다음 글자가 앞에 들어감.
    assert insp.text_edit.textCursor().position() == 1


def test_set_effect_with_different_text_updates_widget(qtbot):
    """text 가 다르면 정상적으로 setPlainText — 외부 변경 반영."""
    insp = CaptionInspector()
    qtbot.addWidget(insp)
    eff = _make_caption("a")
    insp.set_effect(eff)
    # 다른 텍스트로 외부에서 갱신 (예: undo/redo, MCP 등).
    from dataclasses import replace
    new_eff = replace(eff, text="b")
    insp.set_effect(new_eff)
    assert insp.text_edit.toPlainText() == "b"


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
