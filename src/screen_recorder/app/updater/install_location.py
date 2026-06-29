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


def want_code_patch(manifest: Manifest, writable: bool) -> bool:
    """30MB 코드 패치를 쓸 조건: code_url 존재 AND 설치폴더 쓰기가능."""
    return bool(manifest.code_url) and writable


def select_download(manifest: Manifest, writable: bool) -> tuple[str, str, str]:
    """(kind, url, sha256) 반환. kind='code' 또는 'full'."""
    if want_code_patch(manifest, writable):
        return "code", manifest.code_url, manifest.code_sha256
    return "full", manifest.full_url, manifest.full_sha256
