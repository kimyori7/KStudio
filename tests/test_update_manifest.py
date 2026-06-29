import dataclasses
import json
import pytest
from screen_recorder.app.updater.manifest import parse_manifest, Manifest, ManifestError

_FULL_ONLY = {
    "version": "0.1.5", "notes": "버그픽스",
    "full_url": "https://x/Setup.exe", "full_sha256": "a" * 64,
}
_WITH_CODE = {**_FULL_ONLY, "code_url": "https://x/KStudio.exe",
              "code_sha256": "b" * 64, "internal_hash": "deadbeef"}


def test_parse_full_only():
    m = parse_manifest(_FULL_ONLY)
    assert m.version == "0.1.5"
    assert m.full_url.endswith("Setup.exe")
    assert m.code_url == ""          # 선택 필드 기본값
    assert m.mandatory is False


def test_parse_with_code():
    m = parse_manifest(_WITH_CODE)
    assert m.code_url.endswith("KStudio.exe")
    assert m.code_sha256 == "b" * 64
    assert m.internal_hash == "deadbeef"


def test_parse_accepts_bytes_and_str():
    raw = json.dumps(_FULL_ONLY)
    assert parse_manifest(raw).version == "0.1.5"
    assert parse_manifest(raw.encode("utf-8")).version == "0.1.5"


def test_missing_required_field_raises():
    for key in ("version", "full_url", "full_sha256"):
        bad = {k: v for k, v in _FULL_ONLY.items() if k != key}
        with pytest.raises(ManifestError):
            parse_manifest(bad)


def test_bad_sha256_raises():
    with pytest.raises(ManifestError):
        parse_manifest({**_FULL_ONLY, "full_sha256": "xyz"})  # 64 hex 아님


def test_code_url_without_sha_raises():
    bad = {**_FULL_ONLY, "code_url": "https://x/KStudio.exe"}  # code_sha256 없음
    with pytest.raises(ManifestError):
        parse_manifest(bad)


def test_manifest_is_frozen():
    m = parse_manifest(_FULL_ONLY)
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.version = "9.9.9"   # frozen
