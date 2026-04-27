from pathlib import Path
import pytest
from PySide6.QtGui import QImage, QColor

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_tool_change_propagates_to_active_canvas(w):
    w._on_screenshot_captured(_img(), "region")
    w._on_tool_changed("rect")
    tab = w.tab_area.currentWidget()
    assert tab.canvas.current_tool().name == "rect"


def test_color_change_propagates(w):
    w._on_screenshot_captured(_img(), "region")
    w._on_color_changed(QColor("#00FF00"))
    assert w.app_settings.annotation.last_color.upper() == "#00FF00"


def test_save_creates_file(w, tmp_path):
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    files = list(tmp_path.glob("*.png"))
    assert len(files) == 1


def test_copy_to_clipboard(w, qtbot):
    from PySide6.QtWidgets import QApplication
    w._on_screenshot_captured(_img(), "region")
    w._copy_current_screenshot()
    cb = QApplication.clipboard()
    assert not cb.image().isNull()
