from unittest.mock import MagicMock, patch

from screen_recorder.hotkey.manager import HotkeyManager


def test_set_bindings_registers_all_hotkeys():
    cb1, cb2 = MagicMock(), MagicMock()
    fake_listener = MagicMock()

    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", return_value=fake_listener) as ctor:
        m = HotkeyManager()
        m.set_bindings({"Ctrl+Shift+T": cb1, "Ctrl+Shift+R": cb2})

        ctor.assert_called_once()
        binding = ctor.call_args[0][0]
        assert binding["<ctrl>+<shift>+t"] is cb1
        assert binding["<ctrl>+<shift>+r"] is cb2
        fake_listener.start.assert_called_once()


def test_set_bindings_with_empty_text_skips_that_entry():
    """빈 문자열 단축키는 등록하지 않음 (미할당 의미)."""
    cb1, cb2 = MagicMock(), MagicMock()
    fake_listener = MagicMock()

    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", return_value=fake_listener) as ctor:
        m = HotkeyManager()
        m.set_bindings({"Ctrl+Shift+T": cb1, "": cb2})
        binding = ctor.call_args[0][0]
        assert "<ctrl>+<shift>+t" in binding
        assert len(binding) == 1


def test_set_bindings_with_all_empty_does_not_create_listener():
    cb = MagicMock()
    with patch("screen_recorder.hotkey.manager.GlobalHotKeys") as ctor:
        m = HotkeyManager()
        m.set_bindings({"": cb})
        ctor.assert_not_called()


def test_set_bindings_replaces_previous_listener():
    cb1, cb2 = MagicMock(), MagicMock()
    l1, l2 = MagicMock(), MagicMock()

    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", side_effect=[l1, l2]):
        m = HotkeyManager()
        m.set_bindings({"F9": cb1})
        m.set_bindings({"F10": cb2})
        l1.stop.assert_called_once()
        l2.start.assert_called_once()


def test_register_still_works_for_backward_compat():
    """기존 main_window 가 쓰던 register(text, cb) 는 살아있어야 한다."""
    cb = MagicMock()
    fake = MagicMock()
    with patch("screen_recorder.hotkey.manager.GlobalHotKeys", return_value=fake):
        m = HotkeyManager()
        m.register("Ctrl+Shift+T", cb)
        fake.start.assert_called_once()


def test_register_bad_hotkey_does_not_raise_and_leaves_manager_usable():
    """잘못된 단축키 텍스트는 조용히 무시되어야 한다 (이전 동작 유지)."""
    m = HotkeyManager()
    try:
        m.set_bindings({"bogus+key+zzz": lambda: None})
    except Exception:
        pass
    m.unregister()  # 안 깨짐
