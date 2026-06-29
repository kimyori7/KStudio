"""직전 코드 패치가 남긴 KStudio.exe.old 청소. main() 최상단에서 best-effort 호출."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_old_exe(install_dir: Path, exe_name: str = "KStudio.exe") -> None:
    """<exe>.old 가 있으면 삭제. 실패(아직 잠김 등)해도 조용히 — 다음 실행에 재시도."""
    old = install_dir / (exe_name + ".old")
    if not old.exists():
        return
    try:
        old.unlink()
        logger.info("이전 코드패치 잔여 파일 청소: %s", old)
    except OSError:
        logger.debug("'%s' 아직 청소 못 함(잠김?) — 다음 실행에 재시도", old, exc_info=True)
