from unittest.mock import MagicMock, patch

from screen_recorder.hotkey.manager import HotkeyManager


def test_set_bindings_registers_each_non_empty_hotkey(qtbot):
    cb1, cb2 = MagicMock(), MagicMock()
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.set_bindings({"Ctrl+Shift+T": cb1, "Ctrl+Shift+R": cb2})
        # 두 개 모두 등록 시도
        assert user32_mock.RegisterHotKey.call_count == 2


def test_set_bindings_with_empty_text_skips_that_entry(qtbot):
    cb1, cb2 = MagicMock(), MagicMock()
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.set_bindings({"Ctrl+Shift+T": cb1, "": cb2})
        assert user32_mock.RegisterHotKey.call_count == 1


def test_set_bindings_with_all_empty_does_not_register(qtbot):
    cb = MagicMock()
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.set_bindings({"": cb})
        user32_mock.RegisterHotKey.assert_not_called()


def test_set_bindings_replaces_previous(qtbot):
    cb1, cb2 = MagicMock(), MagicMock()
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 1
        m = HotkeyManager()
        m.set_bindings({"F9": cb1})
        m.set_bindings({"F10": cb2})
        # 첫 번째가 unregister 되어야 함
        assert user32_mock.UnregisterHotKey.call_count >= 1
        # 두 번째가 등록되어야 함
        assert user32_mock.RegisterHotKey.call_count == 2


def test_register_bad_hotkey_does_not_raise(qtbot):
    m = HotkeyManager()
    # 파싱 실패는 조용히 스킵
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        m.set_bindings({"bogus+key+zzz": lambda: None})
        user32_mock.RegisterHotKey.assert_not_called()
    m.unregister()  # 안 깨짐


def test_failed_registration_skipped(qtbot):
    """RegisterHotKey 가 실패(다른 앱이 선점)하면 해당 id는 저장 안 됨."""
    cb = MagicMock()
    with patch("screen_recorder.hotkey.manager._user32") as user32_mock:
        user32_mock.RegisterHotKey.return_value = 0  # 실패
        m = HotkeyManager()
        m.set_bindings({"Ctrl+Shift+T": cb})
        # 등록 시도는 했지만 성공 못했으므로 ids 비어있음
        assert len(m._ids) == 0
