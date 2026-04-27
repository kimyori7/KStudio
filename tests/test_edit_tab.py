"""EditTab — 스크린샷 + 외부 파일 공통 편집 탭."""
from __future__ import annotations
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_from_screenshot_creates_layers(qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(50, 40, 0xFFFF0000), source_label="region")
    qtbot.addWidget(tab)
    assert len(tab.stack.layers) == 2  # ImageLayer + AnnotationLayer
    assert tab.source_label() == "region"
    assert tab.is_saved() is False


def test_from_file_raster(tmp_path: Path, qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    p = tmp_path / "x.png"
    _solid(30, 20, 0xFF00FF00).save(str(p), "PNG")
    tab = EditTab.from_file(p)
    qtbot.addWidget(tab)
    assert tab.stack.canvas_size == QSize(30, 20)
    assert len(tab.stack.layers) == 2


def test_from_file_kstudio_round_trip(tmp_path: Path, qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.format import write_kstudio
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20, 0xFFFF0000)))
    out = tmp_path / "x.kstudio"
    write_kstudio(stack, out)
    tab = EditTab.from_file(out)
    qtbot.addWidget(tab)
    assert tab.stack.canvas_size == QSize(20, 20)


def test_image_returns_composite(qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(20, 20, 0xFF00FF00), source_label="region")
    qtbot.addWidget(tab)
    composite = tab.image()
    assert composite.size() == QSize(20, 20)
    assert QColor(composite.pixel(10, 10)).green() == 255


def test_mark_saved_clears_needs_save(tmp_path: Path, qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(20, 20), source_label="region")
    qtbot.addWidget(tab)
    p = tmp_path / "x.kstudio"
    p.write_bytes(b"")
    tab.mark_saved(p)
    assert tab.is_saved() is True
    assert tab.needs_save() is False
