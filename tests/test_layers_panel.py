"""LayersPanel — 우측 도크 레이어 패널."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_panel_lists_layers_top_first(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bottom", pixmap=_solid(20, 20)))
    stack.add_layer(ImageLayer(id=2, name="top", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    names = panel.layer_names_top_first()
    assert names == ["top", "bottom"]


def test_clicking_row_sets_active_layer(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="a", pixmap=_solid(20, 20)))
    stack.add_layer(ImageLayer(id=2, name="b", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.select_row(0)  # top row → id=2
    assert stack.active_layer_id == 2
    panel.select_row(1)  # → id=1
    assert stack.active_layer_id == 1


def test_panel_updates_when_layer_added(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(20, 20)))
    assert panel.layer_names_top_first() == ["x"]


def test_visibility_toggle_changes_layer(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="x", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    assert layer.visible is True
    panel.toggle_visibility(0)
    assert layer.visible is False


def test_rename_via_api(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="old", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.rename_row(0, "new")
    assert stack.layers[0].name == "new"


def test_add_annotation_button(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.add_annotation_layer()
    assert any(l.name == "레이어" for l in stack.layers)


def test_remove_active_layer_button(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(20, 20)))
    stack.add_layer(ImageLayer(id=2, name="y", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.remove_active_layer()
    assert len(stack.layers) == 1


def test_remove_last_layer_blocked(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(20, 20)))
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.remove_active_layer()  # 마지막 1개 → 차단
    assert len(stack.layers) == 1


def test_move_active_layer_up(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from screen_recorder.ui.docks.layers_panel import LayersPanel
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bottom", pixmap=_solid(20, 20)))
    stack.add_layer(ImageLayer(id=2, name="top", pixmap=_solid(20, 20)))
    stack.set_active_layer(1)  # bottom
    panel = LayersPanel(stack)
    qtbot.addWidget(panel)
    panel.move_active_up()
    assert [l.id for l in stack.layers] == [2, 1]
