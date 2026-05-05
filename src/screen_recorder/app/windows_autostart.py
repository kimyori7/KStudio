"""Windows 자동 시작 — 로그인 시 KStudio 를 트레이 상태로 자동 실행.

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 에 항목을 둔다.
- 관리자 권한 불필요 (현재 사용자 한정).
- 패키지된(frozen) 실행 파일에서만 동작 — 개발 모드(python 스크립트)는 no-op.
- 등록 시 `--tray` 인자를 함께 박아 부팅 직후 메인 창은 숨고 트레이 아이콘만 뜨게 한다.
- 실패해도 앱 시작은 막지 않음 (registry 접근 불가 등 환경에서도 죽지 않게).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "KStudio"
_TRAY_ARG = "--tray"

logger = logging.getLogger(__name__)


def _frozen_executable_path() -> Optional[Path]:
    """패키지된 KStudio.exe 경로. frozen 이 아니면 None."""
    if not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable)
    if not p.exists():
        return None
    return p


def _expected_command(exe: Path) -> str:
    return f'"{exe}" {_TRAY_ARG}'


def is_enabled() -> bool:
    """현재 사용자 레지스트리에 KStudio 자동 시작이 등록돼 있는지."""
    if sys.platform != "win32":
        return False
    exe = _frozen_executable_path()
    if exe is None:
        return False
    try:
        import winreg  # noqa: PLC0415 — Windows 전용
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return str(value) == _expected_command(exe)
    except OSError:
        return False


def enable() -> bool:
    """자동 시작 등록. 이미 같은 경로면 no-op. frozen 이 아니면 False."""
    if sys.platform != "win32":
        return False
    exe = _frozen_executable_path()
    if exe is None:
        return False
    if is_enabled():
        return True
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(
                key, _VALUE_NAME, 0, winreg.REG_SZ, _expected_command(exe)
            )
    except OSError as e:
        logger.warning("자동 시작 등록 실패: %s", e)
        return False
    logger.info("자동 시작 등록: %s", exe)
    return True


def disable() -> bool:
    """자동 시작 해제. 항목이 없어도 True. frozen 이 아니면 False."""
    if sys.platform != "win32":
        return False
    if not getattr(sys, "frozen", False):
        return False
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                return True
    except OSError as e:
        logger.warning("자동 시작 해제 실패: %s", e)
        return False
    logger.info("자동 시작 해제 완료")
    return True


def apply(desired: bool) -> bool:
    """설정값에 맞춰 레지스트리 상태 동기화. 이미 일치하면 no-op."""
    if desired:
        return enable()
    return disable()
