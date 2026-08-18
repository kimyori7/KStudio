from pathlib import Path
from screen_recorder.app.updater.install_location import (
    current_install_dir, is_user_writable, want_code_patch, select_download,
    installed_internal_hash,
)
from screen_recorder.app.updater.manifest import Manifest


def test_current_install_dir_is_existing_dir():
    d = current_install_dir()
    assert d.is_dir()


_FULL = Manifest(version="0.1.5", notes="", full_url="https://x/Setup.exe",
                 full_sha256="a" * 64)
_CODE = Manifest(version="0.1.5", notes="", full_url="https://x/Setup.exe",
                 full_sha256="a" * 64, code_url="https://x/KStudio.exe",
                 code_sha256="b" * 64, internal_hash="h1")


def test_writable_true_on_tmp(tmp_path: Path):
    assert is_user_writable(tmp_path) is True


def test_writable_false_on_nonexistent(tmp_path: Path):
    assert is_user_writable(tmp_path / "does_not_exist") is False


def test_installed_internal_hash_reads_file(tmp_path: Path):
    (tmp_path / "internal_hash.txt").write_text("h1\n", encoding="utf-8")
    assert installed_internal_hash(tmp_path) == "h1"


def test_installed_internal_hash_absent_is_none(tmp_path: Path):
    assert installed_internal_hash(tmp_path) is None


def test_want_code_patch_requires_all_including_hash_match():
    # 일치: code_url + writable + internal_hash 일치 → True
    assert want_code_patch(_CODE, writable=True, installed_internal="h1") is True
    # 권한 없음 → full
    assert want_code_patch(_CODE, writable=False, installed_internal="h1") is False
    # code_url 없음 → full
    assert want_code_patch(_FULL, writable=True, installed_internal="h1") is False


def test_want_code_patch_blocks_on_hash_mismatch():
    # skip-version 함정: 설치된 _internal 이 다르면(=의존성 다름) 코드패치 거부.
    assert want_code_patch(_CODE, writable=True, installed_internal="DIFFERENT") is False
    # 설치 해시 파일 없음(옛 설치) → 거부(전체 인스톨러로 안전).
    assert want_code_patch(_CODE, writable=True, installed_internal=None) is False


def test_select_download_code_on_match(tmp_path: Path):
    kind, url, sha = select_download(_CODE, writable=True, installed_internal="h1")
    assert kind == "code"
    assert url.endswith("KStudio.exe")
    assert sha == "b" * 64


def test_select_download_full_on_mismatch_or_nonwritable():
    # 해시 불일치 → full
    assert select_download(_CODE, writable=True, installed_internal="X")[0] == "full"
    # 권한 없음 → full
    kind, url, sha = select_download(_CODE, writable=False, installed_internal="h1")
    assert kind == "full"
    assert url.endswith("Setup.exe")
    assert sha == "a" * 64
    # code_url 없는 manifest → full
    assert select_download(_FULL, writable=True, installed_internal="h1")[0] == "full"


def test_is_user_writable_returns_false_fast_when_denied(tmp_path, monkeypatch):
    """쓰기 거부 폴더에서 즉시 False — 재시도 루프에 빠지지 않아야 한다.

    회귀(2026-08-18): NamedTemporaryFile 을 쓰던 구현은 Windows 에서 PermissionError 를
    "이름 충돌"로 오해해 TMP_MAX 번 재시도했고, Program Files 설치본에서 「새 버전 받기」
    를 누르면 앱이 수 분간 응답 없음이 됐다. 열기 시도는 한 번뿐이어야 한다.
    """
    import builtins
    from screen_recorder.app.updater import install_location as loc

    attempts = []
    real_open = builtins.open

    def denying_open(file, *args, **kwargs):
        if ".kstudio_probe_" in str(file):
            attempts.append(file)
            raise PermissionError(13, "Access is denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denying_open)
    assert loc.is_user_writable(tmp_path) is False
    assert len(attempts) == 1, f"열기 시도가 {len(attempts)}회 — 한 번만 시도해야 함"


def test_is_user_writable_leaves_no_probe_file(tmp_path):
    """성공 경로에서도 프로브 파일이 남지 않아야 한다."""
    from screen_recorder.app.updater.install_location import is_user_writable

    before = set(p.name for p in tmp_path.iterdir())
    assert is_user_writable(tmp_path) is True
    assert set(p.name for p in tmp_path.iterdir()) == before
