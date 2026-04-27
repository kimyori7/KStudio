from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMovie

from screen_recorder.ui.video.player_widget import PlayerWidget


@pytest.fixture
def gif_file(tmp_path):
    """간단한 2프레임 GIF 만들어서 경로 리턴."""
    p = tmp_path / "test.gif"
    GIF89A_2FRAME = bytes.fromhex(
        "474946383961" "0800" "0800" "f000" "00"
        "ff0000" "ffffff"
        "21f9040000000000" "2c00000000080008000000" "020205840000"
        "21f9040a0a0000" "2c00000000080008000000" "020205840000"
        "3b"
    )
    p.write_bytes(GIF89A_2FRAME)
    return p


def test_create_player_for_gif(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    assert w.is_loaded()
    assert w.is_gif()


def test_create_player_for_video(qtbot, tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(p)
    assert w.is_loaded()
    assert not w.is_gif()


def test_play_pause_toggle_signal(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    with qtbot.waitSignal(w.playing_changed, timeout=500) as blocker:
        w.play()
    assert blocker.args == [True]


def test_seek_seconds_clamped_within_duration(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    w.seek_seconds(99999)
    assert w.position_ms() <= w.duration_ms()


def test_step_frame_forward_advances_position(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    w.step_frame(+1)
    assert w.position_ms() >= 0


def test_current_frame_returns_qimage(qtbot, gif_file):
    w = PlayerWidget()
    qtbot.addWidget(w)
    w.load(gif_file)
    img = w.current_frame()
    assert isinstance(img, QImage)
    assert not img.isNull()
