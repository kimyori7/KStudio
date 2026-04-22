from unittest.mock import MagicMock, patch

from screen_recorder.hotkey.manager import HotkeyManager


def test_register_creates_pynput_listener_with_parsed_keys():
    callback = MagicMock()
    fake_listener = MagicMock()

    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", return_value=fake_listener) as ctor:
        m = HotkeyManager()
        m.register("Ctrl+Shift+R", callback)

        ctor.assert_called_once()
        binding = ctor.call_args[0][0]
        assert "<ctrl>+<shift>+r" in binding
        fake_listener.start.assert_called_once()


def test_register_again_stops_previous():
    fake1, fake2 = MagicMock(), MagicMock()

    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", side_effect=[fake1, fake2]):
        m = HotkeyManager()
        m.register("F9", lambda: None)
        m.register("F8", lambda: None)
        fake1.stop.assert_called_once()
        fake2.start.assert_called_once()


def test_unregister_stops_listener():
    fake = MagicMock()
    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", return_value=fake):
        m = HotkeyManager()
        m.register("F9", lambda: None)
        m.unregister()
        fake.stop.assert_called_once()
