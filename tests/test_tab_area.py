import pytest
from PySide6.QtGui import QImage
from screen_recorder.core.settings import PlayerSettings
from screen_recorder.ui.mode_controller import AppMode, ModeController
from screen_recorder.ui.tab_area import TabArea


def _img() -> QImage:
    img = QImage(16, 16, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def gif_file(tmp_path):
    """Pillow-generated valid 2-frame GIF (matches test_player_widget pattern)."""
    from PIL import Image
    p = tmp_path / "x.gif"
    f1 = Image.new("P", (8, 8), 0)
    f2 = Image.new("P", (8, 8), 1)
    palette = [255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6)
    f1.putpalette(palette)
    f2.putpalette(palette)
    f1.save(p, format="GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return p


def test_add_screenshot_creates_tab(qtbot):
    mc = ModeController()
    ta = TabArea(mc, PlayerSettings())
    qtbot.addWidget(ta)
    tid = ta.add_screenshot(image=_img(), source_label="region", entry_id=1)
    assert ta.count_visible() == 1
    assert tid is not None


def test_active_tab_drives_mode(qtbot):
    mc = ModeController()
    ta = TabArea(mc, PlayerSettings())
    qtbot.addWidget(ta)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=1)
    assert mc.mode() is AppMode.IMAGE


def test_video_tab_filtered_when_image_mode(qtbot, gif_file):
    mc = ModeController()
    ta = TabArea(mc, PlayerSettings())
    qtbot.addWidget(ta)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=1)
    ta.add_video(path=gif_file, source_label="region", duration_ms=200, entry_id=2)
    assert mc.mode() is AppMode.VIDEO
    assert ta.count_visible() == 1


def test_switch_mode_filters_strip(qtbot, gif_file):
    mc = ModeController()
    ta = TabArea(mc, PlayerSettings())
    qtbot.addWidget(ta)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=1)
    ta.add_video(path=gif_file, source_label="region", duration_ms=200, entry_id=2)
    mc.set_mode(AppMode.IMAGE)
    assert ta.count_visible() == 1


def test_focus_entry_switches_to_existing_tab(qtbot):
    mc = ModeController()
    ta = TabArea(mc, PlayerSettings())
    qtbot.addWidget(ta)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=10)
    ta.add_screenshot(image=_img(), source_label="full", entry_id=20)
    ta.focus_entry(10)
    assert ta.current_entry_id() == 10
