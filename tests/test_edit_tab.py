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
    """2 레이어 — 투명 배경 + 사진. 주석 레이어는 도구 사용 시점에 자동 생성됨."""
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.image_layer import ImageLayer
    tab = EditTab.from_screenshot(_solid(50, 40, 0xFFFF0000), source_label="region")
    qtbot.addWidget(tab)
    assert len(tab.stack.layers) == 2
    assert isinstance(tab.stack.layers[0], ImageLayer)        # 투명 배경
    assert isinstance(tab.stack.layers[1], ImageLayer)        # 사진
    # 캡처 시 배경은 투명 — 알파가 0 이어야 한다.
    bg_px = tab.stack.layers[0].pixmap.pixel(0, 0)
    assert (bg_px >> 24) & 0xFF == 0
    # 활성 레이어는 사진(두 번째 ImageLayer).
    assert tab.stack.active_layer_id == tab.stack.layers[1].id
    assert tab.source_label() == "region"
    assert tab.is_saved() is False


def test_from_file_raster(tmp_path: Path, qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    p = tmp_path / "x.png"
    _solid(30, 20, 0xFF00FF00).save(str(p), "PNG")
    tab = EditTab.from_file(p)
    qtbot.addWidget(tab)
    assert tab.stack.canvas_size == QSize(30, 20)
    # 투명 배경 + 사진 (주석은 도구 사용 시점에 자동 생성).
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


def test_delete_selection_clears_pixels_in_active_image_layer(qtbot):
    """selection 영역 + delete_selection → 활성 ImageLayer 그 영역만 transparent.

    from_screenshot 가 [투명 배경, 사진] 두 레이어를 만들고 사진을 활성으로 둔다 —
    delete_selection 은 활성 레이어(=사진) 의 영역을 비운다.
    """
    from PySide6.QtCore import QRect
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.image_layer import ImageLayer
    tab = EditTab.from_screenshot(_solid(30, 30, 0xFF00FF00), source_label="region")
    qtbot.addWidget(tab)
    photo = tab.stack.active_layer()
    assert isinstance(photo, ImageLayer)
    tab.selection.set_rect(QRect(5, 5, 10, 10))
    tab.delete_selection()
    # 영역 안 픽셀은 알파 0, 바깥은 그대로 (사진은 원래 알파 255).
    assert (photo.pixmap.pixel(10, 10) >> 24) & 0xFF == 0
    assert (photo.pixmap.pixel(0, 0) >> 24) & 0xFF == 255
    # selection 은 자동으로 해제
    assert tab.selection.has_selection() is False


def test_delete_selection_no_op_without_selection(qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(20, 20, 0xFF00FF00), source_label="region")
    qtbot.addWidget(tab)
    # selection 이 없으니 undo_stack 에 아무것도 안 쌓여야 한다.
    assert tab.undo_stack.count() == 0
    tab.delete_selection()
    assert tab.undo_stack.count() == 0


def test_capture_does_not_create_annotation_layer(qtbot):
    """캡처/파일 열기 직후엔 AnnotationLayer 가 없어야 한다 (사용자가 도구를 쓸 때만 생성)."""
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.annotation_layer import AnnotationLayer
    tab = EditTab.from_screenshot(_solid(20, 20), source_label="region")
    qtbot.addWidget(tab)
    has_ann = any(isinstance(l, AnnotationLayer) for l in tab.stack.layers)
    assert has_ann is False


def test_canvas_delete_key_emits_delete_request(qtbot):
    """캔버스가 포커스를 가진 상태에서 Del → delete_selection_requested 시그널."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(30, 30, 0xFF0000FF), source_label="region")
    qtbot.addWidget(tab)
    tab.selection.set_rect(QRect(5, 5, 10, 10))
    with qtbot.waitSignal(tab.canvas.delete_selection_requested, timeout=500):
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        tab.canvas.keyPressEvent(ev)


def test_from_blank_default_is_transparent_background(qtbot):
    """from_blank 기본은 투명 배경 1 레이어 (주석은 자동 생성하지 않음)."""
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.image_layer import ImageLayer
    from PySide6.QtCore import QSize
    tab = EditTab.from_blank(QSize(40, 30))
    qtbot.addWidget(tab)
    assert len(tab.stack.layers) == 1
    bg = tab.stack.layers[0]
    assert isinstance(bg, ImageLayer)
    # 기본 fill_white=False 이므로 알파 0.
    assert (bg.pixmap.pixel(5, 5) >> 24) & 0xFF == 0
    assert tab.stack.active_layer_id == bg.id


def test_from_blank_with_white_background(qtbot):
    """fill_white=True 면 흰색 배경 1 레이어."""
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.image_layer import ImageLayer
    from PySide6.QtCore import QSize
    tab = EditTab.from_blank(QSize(40, 30), fill_white=True)
    qtbot.addWidget(tab)
    assert len(tab.stack.layers) == 1
    bg = tab.stack.layers[0]
    assert isinstance(bg, ImageLayer)
    px = bg.pixmap.pixel(5, 5)
    assert QColor(px).red() == 255
    assert QColor(px).green() == 255
    assert QColor(px).blue() == 255


def test_canvas_delete_key_no_emit_without_selection(qtbot):
    """selection 이 없으면 Del 을 눌러도 신호가 안 나가야 함."""
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from screen_recorder.ui.edit_tab import EditTab
    tab = EditTab.from_screenshot(_solid(30, 30, 0xFF0000FF), source_label="region")
    qtbot.addWidget(tab)
    with qtbot.assertNotEmitted(tab.canvas.delete_selection_requested):
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
        tab.canvas.keyPressEvent(ev)
