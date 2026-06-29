"""SemVer 비교 — 순수. updater 전용 독립 구현(스크립트 결합 회피)."""
from __future__ import annotations

import re

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(s: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(s.strip())
    if not m:
        raise ValueError(f"SemVer(X.Y.Z) 형식이 아님: {s!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_newer(remote: str, current: str) -> bool:
    """remote 가 current 보다 엄격히 크면 True. 파싱 불가하면 안전하게 False."""
    try:
        return parse_semver(remote) > parse_semver(current)
    except ValueError:
        return False
