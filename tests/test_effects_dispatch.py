"""effects.types — type 문자열 ↔ 클래스 dispatch."""
import pytest
from screen_recorder.effects.types import EFFECT_CLASSES, effect_class_for


def test_dispatch_has_all_types():
    assert set(EFFECT_CLASSES.keys()) == {"caption", "speed", "zoom", "broll", "cut", "arrow", "rect"}


def test_dispatch_returns_correct_class():
    from screen_recorder.effects.types.caption import CaptionEffect
    from screen_recorder.effects.types.cut import CutEffect
    assert effect_class_for("caption") is CaptionEffect
    assert effect_class_for("cut") is CutEffect


def test_dispatch_unknown_type_raises():
    with pytest.raises(KeyError, match="unknown effect type"):
        effect_class_for("magic-wand")
