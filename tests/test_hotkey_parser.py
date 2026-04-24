import pytest

from screen_recorder.hotkey.parser import parse_hotkey_to_vk, HotkeyParseError


def test_parse_to_vk_ctrl_shift_letter():
    mods, vk = parse_hotkey_to_vk("Ctrl+Shift+R")
    assert mods == 0x02 | 0x04  # MOD_CONTROL | MOD_SHIFT
    assert vk == ord("R")


def test_parse_to_vk_f_key():
    mods, vk = parse_hotkey_to_vk("F9")
    assert mods == 0
    assert vk == 0x70 + 8  # VK_F9


def test_parse_to_vk_alt_win_t():
    mods, vk = parse_hotkey_to_vk("Alt+Win+T")
    assert mods == 0x01 | 0x08  # MOD_ALT | MOD_WIN
    assert vk == ord("T")


def test_parse_to_vk_printscreen():
    mods, vk = parse_hotkey_to_vk("PrintScreen")
    assert mods == 0
    assert vk == 0x2C


def test_parse_to_vk_case_insensitive():
    mods, vk = parse_hotkey_to_vk("CTRL+SHIFT+r")
    assert mods == 0x02 | 0x04
    assert vk == ord("R")


def test_parse_to_vk_whitespace_tolerated():
    mods, vk = parse_hotkey_to_vk(" Ctrl + Shift + R ")
    assert mods == 0x02 | 0x04
    assert vk == ord("R")


def test_parse_to_vk_rejects_multi_main_keys():
    with pytest.raises(HotkeyParseError):
        parse_hotkey_to_vk("Ctrl+R+T")  # 두 메인 키


def test_parse_to_vk_rejects_empty():
    with pytest.raises(HotkeyParseError):
        parse_hotkey_to_vk("")


def test_parse_to_vk_rejects_unknown_token():
    with pytest.raises(HotkeyParseError):
        parse_hotkey_to_vk("Ctrl+Foo")
