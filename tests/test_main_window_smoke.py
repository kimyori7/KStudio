from pathlib import Path
import pytest
from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


@pytest.fixture
def ffmpeg_stub(tmp_path):
    p = tmp_path / "ffmpeg.exe"
    p.write_bytes(b"")
    return p


def test_main_window_constructs(qtbot, ffmpeg_stub):
    s = AppSettings()
    w = MainWindow(s, ffmpeg_stub)
    qtbot.addWidget(w)
    assert w.menuBar() is w.menu_bar
    assert w.tab_area is not None
    assert w.library_panel is not None
    assert w.record_status_panel is not None
    assert w.tool_palette is not None
