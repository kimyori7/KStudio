"""파일명 패턴 토큰 치환과 충돌 회피."""
from datetime import datetime
from pathlib import Path
import re

_VALID_TOKENS = {"date", "time", "mode", "target"}


def build_filename(
    pattern: str,
    when: datetime,
    mode: str,
    target: str,
    extension: str,
) -> str:
    """패턴에 토큰을 치환하고 확장자를 붙여 파일명 문자열을 반환."""
    used = set(re.findall(r"\{(\w+)\}", pattern))
    unknown = used - _VALID_TOKENS
    if unknown:
        raise ValueError(f"unknown token(s): {sorted(unknown)}")

    body = pattern.format(
        date=when.strftime("%Y%m%d"),
        time=when.strftime("%H%M%S"),
        mode=mode,
        target=target,
    )
    return f"{body}.{extension.lstrip('.')}"


def resolve_collision(path: Path) -> Path:
    """동일 파일이 있으면 stem 끝에 _2, _3 ... 를 붙여 반환."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1
