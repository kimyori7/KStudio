"""코드 패치(30MB) 적용 — 실행 중 KStudio.exe 를 self-rename 으로 교체.

Windows 는 실행 중 exe 의 *이름변경* 은 허용한다(FILE_SHARE_DELETE). 그래서 별도
updater.exe 없이: 현재 exe → .old 로 rename → 새 exe 를 원래 자리로 → 새 걸로 재시작
→ 다음 실행 때 .old 청소(cleanup.py).

⚠️ 재시작 시 single-instance 충돌 회피: spawn_and_quit 호출 *전에* 호출자가 단일인스턴스
서버를 close 해야 하고, 새 프로세스는 '--post-update' 로 try_forward 를 건너뛴다
(Global Constraints / 설계 5번).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

OLD_SUFFIX = ".old"
POST_UPDATE_FLAG = "--post-update"


def swap_exe(new_exe: Path, target_exe: Path) -> None:
    """target_exe→target_exe.old 이름변경 후 new_exe 를 target_exe 자리로 이동.

    기존 .old(이전 패치 잔여)가 있으면 먼저 제거한다.
    """
    old = target_exe.with_name(target_exe.name + OLD_SUFFIX)
    if old.exists():
        old.unlink()                       # 이전 잔여 제거(없으면 rename 실패)
    os.rename(target_exe, old)             # 실행 중 exe 도 이름변경은 허용(win32)
    os.replace(new_exe, target_exe)        # 새 exe 를 원래 경로로(원자적 교체)
    logger.info("코드패치 교체 완료: %s (이전본 → %s)", target_exe, old.name)


def spawn_and_quit(target_exe: Path, app) -> None:
    """새 exe 를 분리 실행(--post-update) 후 현재 앱 종료. ⚠️ OS 동작 — 수동검증."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(target_exe), POST_UPDATE_FLAG], close_fds=True,
                     creationflags=flags)
    logger.info("새 버전 재시작 spawn — 현재 프로세스 종료")
    app.quit()
