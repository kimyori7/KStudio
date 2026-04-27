import io
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from screen_recorder.core.settings import PlayerSettings
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def gif_file(tmp_path):
    """Pillow 으로 생성한 유효한 2프레임 GIF (8×8, 100ms/frame)."""
    p = tmp_path / "test.gif"
    frames = [
        Image.new("RGB", (8, 8), color=(255, 0, 0)).convert("P"),
        Image.new("RGB", (8, 8), color=(255, 255, 255)).convert("P"),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True,
        append_images=[frames[1]], loop=0, duration=100,
    )
    p.write_bytes(buf.getvalue())
    return p


def test_video_tab_loads_file(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    assert tab.player.is_loaded()


def test_space_key_toggles_play(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    with qtbot.waitSignal(tab.player.playing_changed, timeout=500):
        qtbot.keyPress(tab, Qt.Key_Space)


def test_arrow_right_uses_skip_seconds(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=2)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right)
    assert captured == [2]


def test_shift_arrow_uses_medium_skip(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=1, skip_medium_seconds=5)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right, modifier=Qt.ShiftModifier)
    assert captured == [5]


def test_ctrl_arrow_uses_large_skip(qtbot, gif_file, monkeypatch):
    settings = PlayerSettings(skip_seconds=1, skip_large_seconds=10)
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=10000,
                   player_settings=settings)
    qtbot.addWidget(tab)
    captured: list[float] = []
    monkeypatch.setattr(tab.player, "seek_seconds", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Right, modifier=Qt.ControlModifier)
    assert captured == [10]


def test_comma_period_keys_step_frame(qtbot, gif_file, monkeypatch):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    captured: list[int] = []
    monkeypatch.setattr(tab.player, "step_frame", lambda d: captured.append(d))
    tab.show()
    qtbot.waitExposed(tab)
    tab.setFocus()
    qtbot.keyPress(tab, Qt.Key_Period)
    qtbot.keyPress(tab, Qt.Key_Comma)
    assert captured == [+1, -1]


def test_snapshot_signal(qtbot, gif_file):
    tab = VideoTab(path=gif_file, source_label="region", duration_ms=200,
                   player_settings=PlayerSettings())
    qtbot.addWidget(tab)
    with qtbot.waitSignal(tab.snapshot_requested, timeout=200) as blocker:
        tab.controls.snapshot_btn.click()
    img, label_at = blocker.args
    assert img is not None
    assert "@" in label_at
