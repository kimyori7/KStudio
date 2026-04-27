"""LayerStack — 순수 데이터 + 시그널."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize


@pytest.fixture
def app(qtbot):
    return qtbot


class _DummyLayer:
    """테스트용 Layer 스텁 (Task 5/6 전에 사용)."""
    def __init__(self, lid: int, name: str = "L"):
        self.id = lid
        self.name = name
        self.visible = True
        self.opacity = 1.0


def test_stack_starts_empty(app):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    assert s.layers == []
    assert s.canvas_size == QSize(100, 100)
    assert s.active_layer_id is None


def test_add_layer_emits_layers_changed(app, qtbot):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    with qtbot.waitSignal(s.layers_changed, timeout=1000):
        s.add_layer(_DummyLayer(1, "bg"))
    assert len(s.layers) == 1
    assert s.layers[0].id == 1


def test_add_layer_above_inserts_after(app):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    s.add_layer(_DummyLayer(1, "bottom"))
    s.add_layer(_DummyLayer(2, "top"))
    s.add_layer(_DummyLayer(3, "mid"), above=1)  # id=1 위에 → 인덱스 1
    assert [l.id for l in s.layers] == [1, 3, 2]


def test_remove_layer(app):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    s.add_layer(_DummyLayer(1))
    s.add_layer(_DummyLayer(2))
    s.remove_layer(1)
    assert [l.id for l in s.layers] == [2]


def test_move_layer_up(app):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    s.add_layer(_DummyLayer(1))
    s.add_layer(_DummyLayer(2))
    s.add_layer(_DummyLayer(3))
    s.move_layer(1, new_index=2)  # 맨 아래(0) → 맨 위(2)
    assert [l.id for l in s.layers] == [2, 3, 1]


def test_set_active_layer_emits_signal(app, qtbot):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    s.add_layer(_DummyLayer(1))
    s.add_layer(_DummyLayer(2))
    with qtbot.waitSignal(s.active_layer_changed, timeout=1000) as blocker:
        s.set_active_layer(2)
    assert blocker.args == [2]
    assert s.active_layer_id == 2


def test_set_canvas_size_emits_signal(app, qtbot):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    with qtbot.waitSignal(s.canvas_size_changed, timeout=1000):
        s.set_canvas_size(QSize(200, 150))
    assert s.canvas_size == QSize(200, 150)


def test_get_layer_by_id(app):
    from image_editor.layer_model import LayerStack
    s = LayerStack(canvas_size=QSize(100, 100))
    s.add_layer(_DummyLayer(7, "x"))
    found = s.get_layer(7)
    assert found is not None and found.name == "x"
    assert s.get_layer(99) is None


def test_layer_base_is_abstract():
    from image_editor.layers.base import Layer
    with pytest.raises(TypeError):
        Layer(id=1, name="x")  # 추상 메서드 미구현
