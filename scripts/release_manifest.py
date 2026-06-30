"""자산 URL + latest.json dict 생성 — 순수. Plan 1 Manifest 스키마를 단일 소스로 재사용."""
from __future__ import annotations

from dataclasses import asdict

# 패키지 Manifest — 스키마 드리프트 방지(런타임/빌드 단일 소스).
from screen_recorder.app.updater.manifest import Manifest

FULL_ASSET = "KStudio-Setup-{version}.exe"
CODE_ASSET = "KStudio.exe"


def asset_url(repo: str, version: str, asset_name: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/{asset_name}"


def build_manifest_dict(
    repo: str,
    version: str,
    notes: str,
    full_sha256: str,
    internal_hash: str,
    code_sha256: str = "",
) -> dict:
    """latest.json 내용(dict). code_sha256 가 있으면 code_url 도 채운다."""
    full_name = FULL_ASSET.format(version=version)
    code_url = asset_url(repo, version, CODE_ASSET) if code_sha256 else ""
    m = Manifest(
        version=version,
        notes=notes,
        full_url=asset_url(repo, version, full_name),
        full_sha256=full_sha256,
        code_url=code_url,
        code_sha256=code_sha256,
        internal_hash=internal_hash,
    )
    return asdict(m)
