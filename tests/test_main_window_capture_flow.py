from pathlib import Path
import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(20, 20, QImage.Format_ARGB32)
    img.fill(0xFFAA1122)
    return img


@pytest.fixture
def gif_file(tmp_path):
    """Pillow-generated valid 2-frame GIF."""
    from PIL import Image
    p = tmp_path / "out.gif"
    f1 = Image.new("P", (8, 8), 0)
    f2 = Image.new("P", (8, 8), 1)
    palette = [255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6)
    f1.putpalette(palette)
    f2.putpalette(palette)
    f1.save(p, format="GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return p


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_screenshot_creates_tab_and_library_entry(w):
    w._on_screenshot_captured(_img(), "region")
    assert w.tab_area.count_visible() == 1
    assert len(w.library_model.entries()) == 1


def test_recording_finished_creates_video_tab(w, gif_file):
    w._on_finished(str(gif_file))
    assert w.tab_area.count_visible() == 1
    assert len(w.library_model.entries()) == 1
    assert w.library_model.entries()[0].kind.value == "video"


def test_library_click_opens_existing_tab(w):
    w._on_screenshot_captured(_img(), "region")
    e = w.library_model.entries()[0]
    w._on_screenshot_captured(_img(), "full")
    assert w.tab_area.current_entry_id() != e.id
    w._open_entry(e.id)
    assert w.tab_area.current_entry_id() == e.id
