from pathlib import Path
import pytest
from PySide6.QtGui import QShortcut
from screen_recorder.ui.main_window import MainWindow
from screen_recorder.ui.docks.layers_panel import LayersPanel
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


def test_layers_panel_in_dock_widget(qtbot):
    """LayersPanel 은 dock 안에 들어 있다 (사용자가 위치 자유 조정 가능)."""
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    panels = win.findChildren(LayersPanel)
    assert len(panels) >= 1
    # layers_dock 의 widget 으로 등록되어 있어야 함
    assert win.layers_dock.widget() is win.layers_panel


def test_editor_shortcuts_registered(qtbot):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    seqs = [s.key().toString() for s in win.findChildren(QShortcut)]
    assert "V" in seqs
    assert "C" in seqs
    assert "Ctrl+Shift+B" in seqs
