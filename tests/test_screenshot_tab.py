from pathlib import Path
from PySide6.QtGui import QImage, QColor

from screen_recorder.ui.screenshot_tab import ScreenshotTab


def test_tab_starts_untouched(qtbot):
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0))

    tab = ScreenshotTab(img)
    qtbot.addWidget(tab)

    assert tab.is_saved() is False
    assert tab.saved_path() is None


def test_mark_saved_records_path(qtbot, tmp_path):
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(0)
    tab = ScreenshotTab(img)
    qtbot.addWidget(tab)

    out = tmp_path / "test.png"
    tab.mark_saved(out)

    assert tab.is_saved() is True
    assert tab.saved_path() == out


def test_image_accessor_returns_source(qtbot):
    img = QImage(50, 50, QImage.Format_ARGB32)
    img.fill(QColor(0, 255, 0))
    tab = ScreenshotTab(img)
    qtbot.addWidget(tab)

    got = tab.image()
    assert got.width() == 50
    assert got.height() == 50


def test_signal_emitted_on_save_state_change(qtbot, tmp_path):
    img = QImage(50, 50, QImage.Format_ARGB32)
    tab = ScreenshotTab(img)
    qtbot.addWidget(tab)

    with qtbot.waitSignal(tab.save_state_changed, timeout=1000):
        tab.mark_saved(tmp_path / "x.png")
