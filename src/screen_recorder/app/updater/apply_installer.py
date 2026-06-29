"""전체 인스톨러(150MB) 적용 — 만능 폴백.

받은 Setup.exe 를 실행한다. .iss 에 CloseApplications=yes / UsePreviousAppDir=yes 가
들어 있어 실행 중 앱을 닫고 같은 폴더에 설치한다. 설치 후 [Run] 의 postinstall 이
KStudio 를 다시 띄운다. Program Files 설치본이면 인스톨러가 알아서 UAC 를 띄운다.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_installer(setup_exe: Path, app) -> None:
    """Setup.exe 실행 후 현재 앱 종료. ⚠️ OS 동작 — 수동검증."""
    subprocess.Popen([str(setup_exe)], close_fds=True)
    logger.info("전체 인스톨러 실행 — 현재 프로세스 종료: %s", setup_exe)
    app.quit()
