from pathlib import Path
from screen_recorder.app.updater.install_location import (
    is_user_writable, want_code_patch, select_download,
)
from screen_recorder.app.updater.manifest import Manifest

_FULL = Manifest(version="0.1.5", notes="", full_url="https://x/Setup.exe",
                 full_sha256="a" * 64)
_CODE = Manifest(version="0.1.5", notes="", full_url="https://x/Setup.exe",
                 full_sha256="a" * 64, code_url="https://x/KStudio.exe",
                 code_sha256="b" * 64)


def test_writable_true_on_tmp(tmp_path: Path):
    assert is_user_writable(tmp_path) is True


def test_writable_false_on_nonexistent(tmp_path: Path):
    assert is_user_writable(tmp_path / "does_not_exist") is False


def test_want_code_patch_requires_both():
    assert want_code_patch(_CODE, writable=True) is True
    assert want_code_patch(_CODE, writable=False) is False    # 권한 없음 → full
    assert want_code_patch(_FULL, writable=True) is False     # code_url 없음 → full


def test_select_download_code(tmp_path: Path):
    kind, url, sha = select_download(_CODE, writable=True)
    assert kind == "code"
    assert url.endswith("KStudio.exe")
    assert sha == "b" * 64


def test_select_download_full_fallback():
    kind, url, sha = select_download(_CODE, writable=False)
    assert kind == "full"
    assert url.endswith("Setup.exe")
    assert sha == "a" * 64
    # code_url 없는 manifest 도 full
    assert select_download(_FULL, writable=True)[0] == "full"
