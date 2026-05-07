"""EmptyInspector + InspectorBase."""
import pytest
from PySide6.QtWidgets import QLabel

from screen_recorder.ui.video.inspectors.base import InspectorBase
from screen_recorder.ui.video.inspectors.empty_inspector import EmptyInspector


def test_empty_inspector_shows_placeholder_text(qtbot):
    w = EmptyInspector()
    qtbot.addWidget(w)
    # 자식 위젯 중 안내 텍스트가 있는 QLabel 이 있어야
    labels = w.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    joined = " ".join(texts)
    assert "선택" in joined  # 한국어 "효과를 선택하면..."


def test_inspector_base_set_effect_signature(qtbot):
    """InspectorBase 는 set_effect(effect) 와 effect_changed 시그널을 가짐."""
    w = InspectorBase()
    qtbot.addWidget(w)
    assert hasattr(w, "set_effect")
    assert hasattr(w, "effect_changed")


def test_inspector_base_set_effect_none_no_crash(qtbot):
    """None 을 줘도 안전 (기본 구현은 no-op)."""
    w = InspectorBase()
    qtbot.addWidget(w)
    w.set_effect(None)
