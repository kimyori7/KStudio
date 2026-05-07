"""InspectorPanel — 우측 도크 컨테이너."""
import pytest

from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.panels.inspector_panel import InspectorPanel
from screen_recorder.ui.video.inspectors.empty_inspector import EmptyInspector


def test_panel_starts_with_empty_inspector(qtbot):
    p = InspectorPanel()
    qtbot.addWidget(p)
    assert isinstance(p.current_inspector(), EmptyInspector)


def test_set_effect_none_keeps_empty(qtbot):
    p = InspectorPanel()
    qtbot.addWidget(p)
    p.set_effect(None)
    assert isinstance(p.current_inspector(), EmptyInspector)


def test_set_effect_caption_falls_back_to_empty_in_stage2(qtbot):
    """Stage 2: 아직 CaptionInspector 가 없어 EmptyInspector 로 fallback."""
    p = InspectorPanel()
    qtbot.addWidget(p)
    e = CaptionEffect(in_ms=0, out_ms=1000, text="hi")
    p.set_effect(e)
    assert isinstance(p.current_inspector(), EmptyInspector)


def test_register_inspector_class(qtbot):
    """Stage 3+ 가 사용할 register API — type → inspector class 등록."""
    from screen_recorder.ui.video.inspectors.base import InspectorBase

    class FakeInspector(InspectorBase):
        pass

    p = InspectorPanel()
    qtbot.addWidget(p)
    p.register_inspector("caption", FakeInspector)
    p.set_effect(CaptionEffect(in_ms=0, out_ms=1000, text="hi"))
    assert isinstance(p.current_inspector(), FakeInspector)


def test_effect_changed_bubbles_from_inspector(qtbot):
    """등록된 인스펙터의 effect_changed 가 패널에서 bubble."""
    from screen_recorder.ui.video.inspectors.base import InspectorBase

    class FakeInspector(InspectorBase):
        pass

    p = InspectorPanel()
    qtbot.addWidget(p)
    p.register_inspector("caption", FakeInspector)
    e = CaptionEffect(in_ms=0, out_ms=1000, text="hi")
    p.set_effect(e)

    new_e = CaptionEffect(id=e.id, in_ms=0, out_ms=2000, text="bye")
    with qtbot.waitSignal(p.effect_changed, timeout=1000) as blocker:
        p.current_inspector().effect_changed.emit(new_e)
    assert blocker.args[0].text == "bye"
