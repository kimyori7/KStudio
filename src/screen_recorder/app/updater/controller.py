"""시작 시 비동기 업데이트 체크 + 동의 시 다운로드·적용 오케스트레이션.

⚠️ 절대 시작을 막지 않음: fetch 는 백그라운드 스레드, 모든 예외를 삼킨다. frozen
빌드에서만 동작(dev/pytest no-op). 재시작 시 single-instance 충돌은 _apply_code 에서
si_server.close() + --post-update 로 처리(Global Constraints).
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from screen_recorder.app.updater import install_location as loc
from screen_recorder.app.updater.download import download_to
from screen_recorder.app.updater.fetch import fetch_manifest
from screen_recorder.app.updater.manifest import Manifest
from screen_recorder.app.updater.version_compare import is_newer

logger = logging.getLogger(__name__)


def should_prompt(manifest: Manifest, current_version: str, skip_version: str) -> bool:
    """새 버전이고 사용자가 '건너뛰기' 안 한 버전이면 True."""
    return is_newer(manifest.version, current_version) and manifest.version != skip_version


def save_skip_version(app_settings, settings_update, version: str) -> None:
    """'이 버전 건너뛰기' — skip_version 기록 + settings.json 저장.

    저장 실패는 로그만 남기고 무시 (다음 실행에 한 번 더 물어볼 뿐 — 치명적이지 않음).
    """
    settings_update.skip_version = version
    try:
        from screen_recorder.core import settings as settings_module
        settings_module.save(app_settings, settings_module.settings_path())
    except Exception:   # noqa: BLE001
        logger.warning("skip_version 저장 실패", exc_info=True)


class UpdateChecker(QObject):
    update_available = Signal(object)   # Manifest

    def __init__(self, manifest_url: str, current_version: str,
                 skip_version: str, parent=None):
        super().__init__(parent)
        self._url = manifest_url
        self._current = current_version
        self._skip = skip_version

    def start(self) -> None:
        threading.Thread(target=self._run, name="UpdateChecker", daemon=True).start()

    def _run(self) -> None:
        try:
            manifest = fetch_manifest(self._url)
            if should_prompt(manifest, self._current, self._skip):
                # 큐 연결(Qt.AutoConnection) — 스레드→GUI 스레드 안전 전달.
                self.update_available.emit(manifest)
        except Exception:   # noqa: BLE001 — 네트워크/형식/타임아웃 전부 조용히 포기
            logger.debug("업데이트 체크 실패(무시)", exc_info=True)


def start_update_check(app, win, settings_update, si_server):
    """frozen 빌드에서만 비동기 체크 시작. dev/pytest 는 no-op(None)."""
    import sys
    if not getattr(sys, "frozen", False):
        return None

    from screen_recorder import __version__

    # RELEASES_REPO — ⚠️ Plan 2 에서 만들 실제 공개 레포로 교체.
    RELEASES_REPO = "kimyori7/KStudio-releases"
    manifest_url = (
        f"https://github.com/{RELEASES_REPO}/releases/latest/download/latest.json"
    )

    checker = UpdateChecker(manifest_url, __version__,
                            settings_update.skip_version, parent=win)

    def _on_update_available(manifest: Manifest) -> None:
        from screen_recorder.ui.update_dialog import UpdateDialog
        dlg = UpdateDialog(__version__, manifest, parent=win)

        def _on_skip() -> None:
            save_skip_version(win.app_settings, settings_update, manifest.version)
            dlg.close()

        dlg.skipped.connect(_on_skip)
        # 클릭 시 다이얼로그가 스스로 DOWNLOADING 으로 전환한 뒤 emit 된다.
        dlg.update_now.connect(
            lambda: _download_and_apply(app, win, si_server, manifest, dlg))
        win._update_dialog = dlg    # GC 방지 (win 수명에 묶음)
        dlg.show()                  # 비블로킹 — exec() 금지 (한 인스턴스가 상태 전환)

    checker.update_available.connect(_on_update_available)
    win._update_checker = checker   # GC 방지 (win 수명에 묶음)
    checker.start()
    return checker


def _download_and_apply(app, win, si_server, manifest: Manifest, dlg) -> None:
    """동의 후: 적절한 자산 다운로드 → 검증 → 코드패치/인스톨러 적용.

    dlg: 이미 DOWNLOADING 상태로 전환된 UpdateDialog (컨트롤러가 생성 안 함).
    """
    import tempfile

    install_dir = loc.current_install_dir()
    writable = loc.is_user_writable(install_dir)
    installed_internal = loc.installed_internal_hash(install_dir)
    kind, url, sha = loc.select_download(manifest, writable, installed_internal)

    # ⚠️ 코드 패치는 install_dir 안에 받는다(KStudio.exe.new). temp 와 install 이 다른
    # 볼륨이면 swap_exe 의 os.replace 가 WinError 17(cross-device)로 실패한다 — 기본
    # LocalAppData 설치는 temp(=AppData\Local)와 같은 볼륨이라 dev PC 에선 통과하고
    # TEMP 가 다른 드라이브로 리다이렉트된 사용자에게만 조용히 실패하는 함정. 코드 패치
    # 경로는 want_code_patch 전제상 install_dir 이 쓰기가능 → install_dir 저장이 안전.
    # 전체 인스톨러는 실행만 하고 replace 안 하므로 temp 로도 무방.
    if kind == "code":
        dest = install_dir / "KStudio.exe.new"
    else:
        dest = Path(tempfile.gettempdir()) / f"KStudio-Setup-{manifest.version}.exe"

    # 다운로드는 백그라운드 스레드, 진행/완료는 GUI 스레드로 마샬링.
    from PySide6.QtCore import QObject as _QO, Signal as _Sig

    class _Worker(_QO):
        progressed = _Sig(int, int)
        done = _Sig(object)        # Path or None(실패)

        def run(self):
            def _cb(d, t):
                self.progressed.emit(d, t)
            try:
                out = download_to(url, dest, sha, progress=_cb)
                self.done.emit(out)
            except Exception:   # noqa: BLE001
                logger.warning("업데이트 다운로드 실패", exc_info=True)
                self.done.emit(None)

    # parent=win 으로 worker 의 스레드 affinity 를 GUI 스레드에 명시 고정한다. 그래야
    # 백그라운드 run() 에서 emit 한 progressed/done 이 AutoConnection 으로 GUI 스레드 큐에
    # 안전하게 전달된다(부모 없이도 GUI 스레드서 생성돼 현재는 맞지만, 호출 위치에 의존하는
    # 암묵 가정을 없애 미래 리팩토링에도 안전하게).
    worker = _Worker(win)
    worker.progressed.connect(dlg.set_progress)

    def _on_done(out_path):
        if dlg.was_canceled():
            # 사용자가 취소 — 적용/재시작 강행하지 않음(편집 중 강제 재시작 = 데이터 유실
            # 처럼 느껴짐). 이미 받은 임시본은 청소.
            dlg.close()
            if out_path is not None:
                try:
                    out_path.unlink()
                except OSError:
                    pass
            return
        if out_path is None:
            dlg.show_error()          # 같은 카드에서 실패 안내 (별도 팝업 없음)
            return
        dlg.close()
        try:
            if kind == "code":
                from screen_recorder.app.updater.apply_code_patch import swap_exe, spawn_and_quit
                swap_exe(out_path, install_dir / "KStudio.exe")  # 위험 작업 먼저(트랜잭션 보장)
                si_server.close()                 # ⚠️ swap 성공 후에만 파이프 해제 — swap 실패 시
                                                  # 파이프가 살아있어 기존 인스턴스가 primary 유지
                spawn_and_quit(install_dir / "KStudio.exe", app)
            else:
                from screen_recorder.app.updater.apply_installer import run_installer
                run_installer(out_path, app)
        except Exception:   # noqa: BLE001 — 코드패치 실패 시 폴백 안내
            logger.error("업데이트 적용 실패", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(win, "KStudio 업데이트",
                                "업데이트 적용에 실패했습니다. 전체 인스톨러로 다시 시도하세요.")

    worker.done.connect(_on_done)
    win._update_worker = worker     # GC 방지
    threading.Thread(target=worker.run, name="UpdateDownload", daemon=True).start()
