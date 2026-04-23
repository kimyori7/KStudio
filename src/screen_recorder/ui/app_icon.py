"""앱 아이콘 헬퍼 — 소스 실행과 PyInstaller 빌드 양쪽에서 동일한 경로 해석."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtGui import QIcon

_cached_icon: QIcon | None = None


def _candidate_paths() -> list[Path]:
    paths: list[Path] = [
        # 소스 실행: <repo>/resources/app_icon.ico
        Path(__file__).resolve().parent.parent.parent.parent / "resources" / "app_icon.ico",
    ]
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: <exe>/_internal/resources/app_icon.ico
        exe_dir = Path(sys.executable).parent
        paths.append(exe_dir / "_internal" / "resources" / "app_icon.ico")
        # PyInstaller onefile / generic
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            paths.append(Path(meipass) / "resources" / "app_icon.ico")
    return paths


def app_icon() -> QIcon:
    """첫 호출 후 캐시. 못 찾으면 빈 QIcon 반환."""
    global _cached_icon
    if _cached_icon is not None:
        return _cached_icon
    for p in _candidate_paths():
        if p.exists():
            _cached_icon = QIcon(str(p))
            return _cached_icon
    _cached_icon = QIcon()
    return _cached_icon
