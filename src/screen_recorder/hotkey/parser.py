"""사용자 친화 단축키 문자열 -> pynput 포맷."""
import string


_MODIFIERS = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "win": "<cmd>",
    "super": "<cmd>",
}


def _normalize_key(token: str) -> str:
    t = token.strip().lower()
    if t in _MODIFIERS:
        return _MODIFIERS[t]
    if t.startswith("f") and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
        return f"<{t}>"
    if len(t) == 1 and t in (string.ascii_lowercase + string.digits):
        return t
    raise HotkeyParseError(f"unknown key token: {token!r}")


def parse_hotkey(text: str) -> str:
    if not text or not text.strip():
        raise HotkeyParseError("empty hotkey string")
    parts = [p for p in text.split("+") if p.strip()]
    if not parts:
        raise HotkeyParseError("no key tokens")
    return "+".join(_normalize_key(p) for p in parts)


class HotkeyParseError(ValueError):
    pass
