"""GitHub Releases manifest(`latest.json`) 파싱 — 순수(네트워크 없음).

이 dataclass가 런타임 plan ↔ 빌드 plan의 유일한 공유 계약이다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ManifestError(ValueError):
    """manifest 형식이 어긋남 — 호출자는 업데이트를 조용히 포기한다."""


@dataclass(frozen=True)
class Manifest:
    version: str
    notes: str
    full_url: str
    full_sha256: str
    code_url: str = ""
    code_sha256: str = ""
    internal_hash: str = ""
    mandatory: bool = False


def _require_str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise ManifestError(f"필수 문자열 필드 누락/빈값: {key!r}")
    return v


def _require_sha(d: dict, key: str) -> str:
    v = _require_str(d, key)
    if not _SHA256_RE.match(v):
        raise ManifestError(f"{key} 는 64자리 hex sha256 이어야 함: {v!r}")
    return v


def parse_manifest(data) -> Manifest:
    """dict | str | bytes → Manifest. 형식 위반은 ManifestError."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ManifestError(f"JSON 파싱 실패: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError("manifest 최상위가 객체(dict)가 아님")

    version = _require_str(data, "version")
    full_url = _require_str(data, "full_url")
    full_sha = _require_sha(data, "full_sha256")
    notes = data.get("notes", "")
    notes = notes if isinstance(notes, str) else ""

    code_url = data.get("code_url", "")
    code_url = code_url if isinstance(code_url, str) else ""
    code_sha = ""
    if code_url:
        code_sha = _require_sha(data, "code_sha256")  # code_url 있으면 sha 필수

    internal_hash = data.get("internal_hash", "")
    internal_hash = internal_hash if isinstance(internal_hash, str) else ""
    mandatory = bool(data.get("mandatory", False))

    return Manifest(
        version=version, notes=notes,
        full_url=full_url, full_sha256=full_sha,
        code_url=code_url, code_sha256=code_sha,
        internal_hash=internal_hash, mandatory=mandatory,
    )
