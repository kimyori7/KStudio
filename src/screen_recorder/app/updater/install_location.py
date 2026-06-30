"""설치 위치 판정 — 코드패치 vs 전체 인스톨러 분기.

위치 이름을 하드코딩(Program Files 등)하지 않고 *실제 쓰기 가능 여부* 로 판정한다
→ 사용자가 어디에 깔든 안전. (설계 7번: 기본 LocalAppData 전환.)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from screen_recorder.app.updater.manifest import Manifest


def current_install_dir() -> Path:
    """실행 중 KStudio.exe 가 있는 폴더. frozen 빌드 기준."""
    return Path(sys.executable).resolve().parent


def is_user_writable(dir_path: Path) -> bool:
    """디렉터리에 실제로 쓸 수 있는지 프로브(고유 임시 파일 생성→자동 삭제).

    Program Files(관리자 폴더)에 비관리자로 깔린 경우 False → 전체 인스톨러 경로로.
    NamedTemporaryFile 을 쓰는 이유: ① 고유 이름이라 동시 프로브가 서로 충돌하지 않고,
    ② with 블록을 벗어나면(쓰기 도중 예외가 나도) 자동 삭제돼 프로브 파일이 남지 않는다.
    """
    try:
        with tempfile.NamedTemporaryFile(dir=dir_path, prefix=".kstudio_probe_") as f:
            f.write(b"x")
        return True
    except OSError:
        return False


def installed_internal_hash(install_dir: Path) -> str | None:
    """설치된 _internal 지문(빌드 때 동봉한 internal_hash.txt). 없으면 None.

    release.py 가 빌드 시 _internal 지문을 KStudio.exe 옆(앱 루트)에 적어 동봉한다.
    이 값이 manifest.internal_hash 와 같아야만 코드 패치가 *현재 설치된* _internal 과
    호환됨이 보장된다(의존성 바뀐 릴리스를 건너뛴 사용자 보호 — 직전 릴리스 기준
    decide_code_patch 만으론 부족). 파일이 없으면(이 기능 이전 설치) None → 코드 패치
    안 함(전체 인스톨러로 안전).
    """
    try:
        v = (install_dir / "internal_hash.txt").read_text(encoding="utf-8").strip()
        return v or None
    except OSError:
        return None


def want_code_patch(manifest: Manifest, writable: bool,
                    installed_internal: str | None) -> bool:
    """30MB 코드 패치 조건: code_url 존재 AND 쓰기가능 AND manifest.internal_hash 가
    *현재 설치된* _internal 지문과 일치. 마지막 조건이 빠지면 의존성이 다른 옛 버전에
    코드만 덮어써 런타임 불일치로 깨진다(skip-version 함정)."""
    return (
        bool(manifest.code_url)
        and writable
        and bool(manifest.internal_hash)
        and manifest.internal_hash == installed_internal
    )


def select_download(manifest: Manifest, writable: bool,
                    installed_internal: str | None) -> tuple[str, str, str]:
    """(kind, url, sha256) 반환. kind='code' 또는 'full'."""
    if want_code_patch(manifest, writable, installed_internal):
        return "code", manifest.code_url, manifest.code_sha256
    return "full", manifest.full_url, manifest.full_sha256
