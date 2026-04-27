"""`.kstudio` (ZIP) 포맷 write + read 라운드트립."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def test_write_creates_zip_with_manifest(tmp_path: Path, qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.format import write_kstudio
    stack = LayerStack(QSize(40, 30))
    stack.add_layer(ImageLayer(id=1, name="사진", pixmap=_solid(40, 30, 0xFF00FF00)))
    stack.add_layer(AnnotationLayer(id=2, name="주석", canvas_size=QSize(40, 30)))

    out = tmp_path / "x.kstudio"
    write_kstudio(stack, out)

    assert out.exists()
    with zipfile.ZipFile(out, "r") as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert "layers/1_image.png" in names
        assert "layers/2_annotation.json" in names
        assert "thumbnail.png" in names
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        assert manifest["format_version"] == 1
        assert manifest["canvas_size"] == [40, 30]
        assert len(manifest["layers"]) == 2


def test_write_includes_mask_when_present(tmp_path: Path, qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.format import write_kstudio
    stack = LayerStack(QSize(20, 20))
    mask = QImage(20, 20, QImage.Format_Grayscale8)
    mask.fill(128)
    stack.add_layer(ImageLayer(id=1, name="x", pixmap=_solid(20, 20), mask=mask))
    out = tmp_path / "x.kstudio"
    write_kstudio(stack, out)
    with zipfile.ZipFile(out, "r") as z:
        assert "layers/1_mask.png" in z.namelist()


def test_round_trip_preserves_layers(tmp_path: Path, qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.format import write_kstudio, read_kstudio
    stack = LayerStack(QSize(40, 30))
    stack.add_layer(ImageLayer(id=1, name="사진", pixmap=_solid(40, 30, 0xFF00FF00)))
    stack.add_layer(AnnotationLayer(id=2, name="주석", canvas_size=QSize(40, 30)))
    out = tmp_path / "x.kstudio"
    write_kstudio(stack, out)

    loaded = read_kstudio(out)
    assert loaded.canvas_size == QSize(40, 30)
    assert len(loaded.layers) == 2
    assert loaded.layers[0].name == "사진"
    assert loaded.layers[1].name == "주석"
    # ImageLayer 픽셀 보존
    assert QColor(loaded.layers[0].pixmap.pixel(5, 5)).green() == 255


def test_corrupt_zip_raises(tmp_path: Path):
    from image_editor.format import read_kstudio
    bad = tmp_path / "bad.kstudio"
    bad.write_bytes(b"NOT A ZIP")
    with pytest.raises(Exception):
        read_kstudio(bad)
