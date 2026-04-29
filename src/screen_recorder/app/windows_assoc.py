"""Windows 파일 연결 — `.kstudio` 확장자를 KStudio 실행 파일과 연결.

HKCU\\Software\\Classes 아래에만 쓰므로 관리자 권한이 필요 없다.
사용자 프로필 단위로만 등록되며, OS 전체에는 영향이 없다.

설계 원칙:
- 패키지된(frozen) 실행 파일에서만 동작. 개발 모드(python 스크립트)에서는
  no-op — 가상환경/스크립트 경로가 휘발성이 커 레지스트리에 박아 두면 위험.
- 매번 자동 등록하지만, 이미 같은 경로가 들어 있으면 쓰기 자체를 생략 (idempotent).
- 실패해도 앱 시작은 막지 않음 (registry 접근 불가 등 환경에서도 죽지 않게).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_PROG_ID = "KStudio.Project"
_EXT = ".kstudio"
_FRIENDLY = "KStudio Project"

logger = logging.getLogger(__name__)


def _frozen_executable_path() -> Optional[Path]:
    """패키지된 KStudio.exe 경로. frozen 이 아니면 None.

    PyInstaller(--onedir/--onefile) 에서 sys.frozen=True, sys.executable 이
    실제 exe 경로를 가리킨다.
    """
    if not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable)
    if not p.exists():
        return None
    return p


def is_associated() -> bool:
    """현재 사용자 레지스트리에 .kstudio 연결이 frozen exe 와 동일하게 등록돼 있는지."""
    exe = _frozen_executable_path()
    if exe is None or sys.platform != "win32":
        return False
    expected_cmd = f'"{exe}" "%1"'
    try:
        import winreg  # noqa: PLC0415 — Windows 전용
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{_PROG_ID}\shell\open\command",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return str(value) == expected_cmd
    except OSError:
        return False


def ensure_associated() -> bool:
    """필요 시 .kstudio 연결을 HKCU 에 등록. 이미 같은 경로면 no-op.

    Windows 가 아니거나 frozen 빌드가 아니면 아무 일도 하지 않고 False 반환.
    실패 시에도 예외를 삼키고 False 반환.
    """
    if sys.platform != "win32":
        return False
    exe = _frozen_executable_path()
    if exe is None:
        return False
    if is_associated():
        return True
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return False

    cmd = f'"{exe}" "%1"'
    icon = f'"{exe}",0'
    try:
        # 1) .kstudio → ProgID
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{_EXT}"
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _PROG_ID)
        # 2) ProgID → 친근한 이름
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{_PROG_ID}"
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _FRIENDLY)
        # 3) 아이콘
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{_PROG_ID}\DefaultIcon"
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, icon)
        # 4) shell open command
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{_PROG_ID}\shell\open\command",
        ) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
    except OSError as e:
        logger.warning("kstudio 확장자 등록 실패: %s", e)
        return False

    # 셸에 변경 알림 (탐색기 아이콘 즉시 갱신)
    try:
        import ctypes  # noqa: PLC0415

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except Exception:  # noqa: BLE001 — 알림 실패는 무시
        pass

    logger.info("kstudio 확장자 등록 완료: %s", exe)
    return True
