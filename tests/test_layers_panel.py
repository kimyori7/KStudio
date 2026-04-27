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
