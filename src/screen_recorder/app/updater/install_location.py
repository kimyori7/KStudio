"""설치 위치 판정 — 코드패치 vs 전체 인스톨러 분기.

위치 이름을 하드코딩(Program Files 등)하지 않고 *실제 쓰기 가능 여부* 로 판정한다
→ 사용자가 어디에 깔든 안전. (설계 7번: 기본 LocalAppData 전환.)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from screen_recorder.app.updater.manifest import Manifest


def current_install_dir() -> Path:
    """실행 중 KStudio.exe 가 있는 폴더. frozen 빌드 기준."""
    return Path(sys.executable).resolve().parent


def is_user_writable(dir_path: Path) -> bool:
    """디렉터리에 실제로 쓸 수 있는지 프로브(파일 1개 생성→삭제).

    Program Files(관리자 폴더)에 비관리자로 깔린 경우 False → 전체 인스톨러 경로로.

    ⚠️ tempfile.NamedTemporaryFile 을 쓰면 안 된다. Windows 에서 쓰기 거부(PermissionError)
    를 만나면 CPython 의 _mkstemp_inner 가 "같은 이름의 디렉터리가 이미 있는 경우"로 보고
    (os.access 는 Windows ACL 을 못 보고 True 를 돌려준다) TMP_MAX 번 재시도한다. Program
    Files 처럼 ACL 로 막힌 폴더에서는 이 재시도가 수 분간 GIL 을 쥔 채 돌아 앱 전체가
    응답 없음이 된다 (2026-08-18 사용자 보고: 「새 버전 받기」 클릭 후 멈춤). 한 번만
    시도하고 실패하면 바로 False 를 돌려준다.

    이름에 PID 를 넣어 여러 인스턴스가 동시에 프로브해도 충돌하지 않게 하고, 성공·실패와
    무관하게 프로브 파일을 지운다.
    """
    probe = Path(dir_path) / f".kstudio_probe_{os.getpid()}"
    try:
        with open(probe, "wb") as f:
            f.write(b"x")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


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
