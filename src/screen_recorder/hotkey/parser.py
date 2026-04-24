"""사용자 친화 단축키 문자열 → Windows RegisterHotKey (mod_flags, vk) 변환."""
import string


# Windows Virtual Key 수식자 플래그
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008

_MODIFIERS_WIN32 = {
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
    "alt": _MOD_ALT,
    "win": _MOD_WIN,
    "super": _MOD_WIN,
}

# 자주 쓰이는 특수 키의 Windows VK 코드
_VK_SPECIAL = {
    "printscreen": 0x2C,  # VK_SNAPSHOT
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "escape": 0x1B,
    "backspace": 0x08,
}


class HotkeyParseError(ValueError):
    pass


def parse_hotkey_to_vk(text: str) -> tuple[int, int]:
    """'Ctrl+Shift+R' → (mod_flags, vk_code) (Windows RegisterHotKey 용)."""
    if not text or not text.strip():
        raise HotkeyParseError("empty hotkey string")
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise HotkeyParseError("no key tokens")

    mod_flags = 0
    key_token: str | None = None
    for p in parts:
        if p in _MODIFIERS_WIN32:
            mod_flags |= _MODIFIERS_WIN32[p]
        else:
            if key_token is not None:
                raise HotkeyParseError(
                    f"multiple non-modifier keys: {key_token!r}, {p!r}"
                )
            key_token = p

    if key_token is None:
        raise HotkeyParseError("no main key")

    vk = _token_to_vk(key_token)
    if vk is None:
        raise HotkeyParseError(f"unknown key token: {key_token!r}")
    return mod_flags, vk


def _token_to_vk(token: str) -> int | None:
    t = token.lower()
    # A-Z: VK == ASCII 'A'..'Z' (0x41..0x5A)
    if len(t) == 1 and t in string.ascii_lowercase:
        return ord(t.upper())
    # 0-9
    if len(t) == 1 and t in string.digits:
        return ord(t)
    # F1-F24
    if t.startswith("f") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)  # VK_F1 = 0x70
    # 특수 키
    if t in _VK_SPECIAL:
        return _VK_SPECIAL[t]
    return None
