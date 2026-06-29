"""파일 다운로드 + sha256 무결성 검증.

코드 서명을 안 하므로 sha256 대조가 유일한 신뢰 닻. 불일치 = 즉시 폐기.
프로그램 내부 urllib 다운로드라 Mark-of-the-Web(Zone.Identifier ADS)가 안 붙어
재실행 시 SmartScreen 경고가 뜨지 않는다(설계 6번).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Optional

from screen_recorder.app.updater import net

_CHUNK = 1 << 16   # 64KB


def sha256_file(path: Path) -> str:
    """파일의 SHA256 해시를 16진수 문자열로 반환."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download_to(
    url: str,
    dest: Path,
    expected_sha256: str,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """url → dest 스트리밍 저장 후 sha256 대조. 불일치면 dest 삭제 + ValueError."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    downloaded = 0
    with net.open_url(url) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        with open(dest, "wb") as f:
            for chunk in iter(lambda: resp.read(_CHUNK), b""):
                f.write(chunk)
                h.update(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
    actual = h.hexdigest()
    if actual.lower() != expected_sha256.lower():
        try:
            dest.unlink()
        except OSError:
            pass
        raise ValueError(
            f"sha256 불일치 — 받은 파일 폐기. expected={expected_sha256} actual={actual}"
        )
    return dest
