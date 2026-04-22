from unittest.mock import MagicMock, patch

from screen_recorder.capture.targets import (
    FullScreenTarget, RegionTarget, WindowTarget, Rect,
)


def test_fullscreen_returns_monitor_rect():
    t = FullScreenTarget(monitor_index=0)
    with patch.object(t, "_get_monitor_rect", return_value=Rect(0, 0, 1920, 1080)):
        assert t.current_rect() == Rect(0, 0, 1920, 1080)


def test_region_returns_fixed_rect():
    t = RegionTarget(Rect(100, 200, 800, 600))
    assert t.current_rect() == Rect(100, 200, 800, 600)
    assert t.current_rect() == Rect(100, 200, 800, 600)


def test_window_target_tracks_moving_window():
    fake_window = MagicMock()
    fake_window.left = 50
    fake_window.top = 60
    fake_window.width = 700
    fake_window.height = 500
    fake_window.isMinimized = False

    t = WindowTarget(window=fake_window)
    assert t.current_rect() == Rect(50, 60, 700, 500)

    fake_window.left = 200
    fake_window.top = 100
    assert t.current_rect() == Rect(200, 100, 700, 500)


def test_window_minimized_returns_none():
    fake_window = MagicMock()
    fake_window.isMinimized = True
    t = WindowTarget(window=fake_window)
    assert t.current_rect() is None
