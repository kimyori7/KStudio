from unittest.mock import MagicMock, patch

from screen_recorder.hotkey.manager import HotkeyManager


def test_register_calls_win32_RegisterHotKey_with_parsed_vk(qtbot):
    callback = MagicMock()

    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1  # success
        m = HotkeyManager()
        m.register("Ctrl+Shift+R", callback)

        user32_mock.RegisterHotKey.assert_called_once()
        args = user32_mock.RegisterHotKey.call_args[0]
        # args: (hwnd, id, modifiers, vk)
        mods = args[2]
        vk = args[3]
        # ctrl(0x02) + shift(0x04) + NOREPEAT(0x4000) = 0x4006
        assert mods == 0x4006
        assert vk == ord("R")


def test_register_again_unregisters_previous(qtbot):
    cb1, cb2 = MagicMock(), MagicMock()

    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.register("F9", cb1)
        m.register("F8", cb2)
        # 두 번 Register, 첫 번째는 Unregister 되어야 함
        assert user32_mock.RegisterHotKey.call_count == 2
        assert user32_mock.UnregisterHotKey.call_count >= 1


def test_unregister_calls_UnregisterHotKey(qtbot):
    cb = MagicMock()

    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.register("F9", cb)
        m.unregister()
        user32_mock.UnregisterHotKey.assert_called_once()
