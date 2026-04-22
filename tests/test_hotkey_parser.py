import pytest

from screen_recorder.hotkey.parser import parse_hotkey, HotkeyParseError


def test_single_function_key():
    assert parse_hotkey("F9") == "<f9>"


def test_modifier_combination():
    assert parse_hotkey("Ctrl+Shift+R") == "<ctrl>+<shift>+r"


def test_modifier_alt():
    assert parse_hotkey("Alt+F4") == "<alt>+<f4>"


def test_case_insensitive():
    assert parse_hotkey("ctrl+shift+r") == "<ctrl>+<shift>+r"
    assert parse_hotkey("CTRL+SHIFT+R") == "<ctrl>+<shift>+r"


def test_whitespace_tolerated():
    assert parse_hotkey(" Ctrl + Shift + R ") == "<ctrl>+<shift>+r"


def test_letter_only():
    assert parse_hotkey("A") == "a"


def test_empty_raises():
    with pytest.raises(HotkeyParseError):
        parse_hotkey("")


def test_unknown_token_raises():
    with pytest.raises(HotkeyParseError):
        parse_hotkey("Ctrl+Foo")
