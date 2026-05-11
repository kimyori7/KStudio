"""QApplication 진입점."""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Qt의 DPI awareness 경고 숨김 (이미 프로세스 DPI가 설정된 경우 Qt가 재설정 못해서 생기는 무해한 경고)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")
# 미디어 백엔드를 ffmpeg 로 명시 (Qt 6.5+ 기본이지만 WMF 로 fallback 되는 환경 방지).
# WMF 는 고배속 재생 시 프레임 스킵이 심하고 UI 정지 사례가 보고되어 ffmpeg 강제.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PySide6.QtWidgets import QApplication, QMessageBox

from screen_recorder.app import windows_assoc, windows_autostart
from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.core.settings import AppSettings, load, save, settings_path
from screen_recorder.ui.main_window import MainWindow

# 부팅 시 자동 시작으로 진입했음을 알리는 플래그 — 메인 창을 숨기고 트레이만 띄운다.
_TRAY_FLAG = "--tray"


SETTINGS_PATH = settings_path()


def build_main_window(
    settings: AppSettings | None = None,
    ffmpeg_path: Path | None = None,
) -> MainWindow:
    """테스트·재사용 가능한 MainWindow 빌더.

    - settings 가 None 이면 디스크에서 로드 (없으면 기본).
    - ffmpeg_path 가 None 이면 find_ffmpeg() 시도, 못 찾으면 더미 경로.
      (테스트 모드에선 ffmpeg 가 없는 환경에서도 창은 떠야 하므로 더미 허용.)
    """
    if settings is None:
        try:
            settings = load(SETTINGS_PATH)
        except (OSError, ValueError):
            settings = AppSettings()
    if ffmpeg_path is None:
        ffmpeg_path = find_ffmpeg() or Path("ffmpeg.exe")
    return MainWindow(settings=settings, ffmpeg_path=ffmpeg_path)


def main() -> int:
    from screen_recorder.core.logging_setup import setup_logging
    setup_logging()
    import logging
    logging.info("KStudio started")
    # 미처리 예외도 로그에 남도록 — 다음 크래시 시 traceback 가 app.log 에 기록되어
    # 같은 자리에서 디버깅 가능 (Qt event loop 안의 슬롯 예외도 default excepthook 경유).
    def _log_uncaught(exc_type, exc_value, exc_tb):
        logging.error("UNCAUGHT EXCEPTION",
                      exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _log_uncaught

    app = QApplication(sys.argv)
    app.setApplicationName("KStudio")
    # 트레이로 숨겨도 마지막 윈도우 닫힘 신호로 종료되지 않도록.
    # (closeEvent 가 hide() 로 우회하지만, 자동 시작 모드에서는 처음부터 창을
    # 한 번도 보여주지 않으므로 이 보호가 더 중요해진다.)
    app.setQuitOnLastWindowClosed(False)
    from screen_recorder.ui.app_icon import app_icon
    from screen_recorder.ui.theme import apply_theme
    app.setWindowIcon(app_icon())
    # 초기 테마는 이미지 모드 — ModeController 의 기본값이 IMAGE 라
    # MainWindow 가 _on_mode_changed 를 발화시키기 전에도 동일 팔레트로 보이게.
    apply_theme(app, "image")

    # Windows 작업표시줄에서 어플 아이콘이 별도로 잡히도록 AppUserModelID 설정
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "COMPANY.kimyori.screen_recorder.1.0"
            )
        except Exception:
            pass

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        QMessageBox.critical(
            None, "ffmpeg 없음",
            "ffmpeg.exe를 찾을 수 없습니다.\n\n"
            "https://www.gyan.dev/ffmpeg/builds/ 에서 받아 PATH에 추가하거나\n"
            "본 앱과 같은 폴더의 bin/ 아래 두세요."
        )
        return 1

    settings = load(SETTINGS_PATH)

    # i18n — settings.preferences.language 에 따라 한국어/영어 결정.
    # i18n_en import 시점에 영문 번역 사전이 자동 등록 (모듈 부팅 사이드이펙트).
    from screen_recorder.core import i18n
    from screen_recorder.core import i18n_en  # noqa: F401  — 사전 등록을 위한 import
    if settings.preferences.language in ("ko", "en"):
        i18n.set_language(settings.preferences.language)  # type: ignore[arg-type]

    win = MainWindow(settings=settings, ffmpeg_path=ffmpeg)

    def on_about_to_quit():
        save(win.app_settings, SETTINGS_PATH)
    app.aboutToQuit.connect(on_about_to_quit)

    # 패키지된 빌드라면 .kstudio 확장자 연결을 한 번 갱신 (HKCU, idempotent).
    windows_assoc.ensure_associated()
    # 자동 시작 레지스트리도 설정값과 동기화 — 사용자가 exe 를 옮긴 경우에도
    # 다음 부팅에 올바른 경로가 등록되도록 매 실행마다 idempotent 하게 적용한다.
    windows_autostart.apply(settings.preferences.autostart)

    # `--tray` 인자로 들어왔으면 메인 창을 숨긴 상태로 시작한다 (트레이만 표시).
    start_in_tray = _TRAY_FLAG in sys.argv[1:]
    if not start_in_tray:
        win.show()

    # 명령행으로 들어온 파일 경로가 있으면 새 탭으로 연다 (탐색기 더블클릭 흐름).
    # 단, 파일을 받은 경우엔 사용자가 그 파일을 보길 원한다는 뜻이므로 트레이 모드라도
    # 창을 띄운다.
    opened_any = False
    for arg in sys.argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        p = Path(arg)
        if p.is_file():
            win._open_path(p)
            opened_any = True
    if start_in_tray and opened_any:
        win.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
