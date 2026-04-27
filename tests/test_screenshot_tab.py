from pathlib import Path
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QColor

from screen_recorder.ui.screenshot_tab import ScreenshotTab
from image_editor.items.rect import RectAnnotationItem
from image_editor.commands import AddAnnotationCommand


def _img(w=50, h=50, color=QColor(255, 0, 0)) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(color)
    return img


def test_tab_starts_untouched(qtbot):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    assert tab.is_saved() is False
    assert tab.saved_path() is None


def test_mark_saved_records_path(qtbot, tmp_path):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    out = tmp_path / "test.png"
    tab.mark_saved(out)
    assert tab.is_saved() is True
    assert tab.saved_path() == out


def test_image_accessor_returns_composite(qtbot):
    """image() 는 주석이 합성된 현재 이미지를 반환 (주석 없으면 원본과 동일 크기)."""
    tab = ScreenshotTab(_img(50, 50))
    qtbot.addWidget(tab)
    got = tab.image()
    assert got.width() == 50
    assert got.height() == 50


def test_signal_emitted_on_save_state_change(qtbot, tmp_path):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    with qtbot.waitSignal(tab.save_state_changed, timeout=1000):
        tab.mark_saved(tmp_path / "x.png")


def test_undo_stack_is_clean_initially(qtbot):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    assert tab.undo_stack.isClean() is True


def test_adding_annotation_makes_stack_dirty(qtbot):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))
    assert tab.undo_stack.isClean() is False


def test_save_sets_stack_clean(qtbot, tmp_path):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))
    tab.mark_saved(tmp_path / "a.png")
    assert tab.undo_stack.isClean() is True


def test_needs_save_combines_saved_and_clean(qtbot, tmp_path):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    # 아직 저장 안 됨 + stack clean
    assert tab.needs_save() is True
    tab.mark_saved(tmp_path / "a.png")
    assert tab.needs_save() is False
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))
    assert tab.needs_save() is True


def test_save_state_signal_on_dirty_to_clean(qtbot, tmp_path):
    tab = ScreenshotTab(_img())
    qtbot.addWidget(tab)
    tab.mark_saved(tmp_path / "a.png")  # 이제 needs_save False
    item = RectAnnotationItem(QRectF(0, 0, 10, 10), QColor("#000"), 2)
    with qtbot.waitSignal(tab.save_state_changed, timeout=500):
        tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))  # dirty 로
