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
from screen_recorder.core import settings as _settings_module
from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow

# 부팅 시 자동 시작으로 진입했음을 알리는 플래그 — 메인 창을 숨기고 트레이만 띄운다.
_TRAY_FLAG = "--tray"


# **주의**: 모듈 import 시점에 한 번 평가하면 테스트 isolate fixture(`isolate_user_settings`)
# 가 적용되기 *이전* 에 실제 경로가 박혀 우회 가능. 회귀 (2026-05-13: pytest 가 사용자
# 실제 settings.json 을 defaults 로 덮어씀). 항상 함수 호출 시점에 평가하도록 변경.
def SETTINGS_PATH() -> Path:
    return _settings_module.settings_path()


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
            settings = _settings_module.load(SETTINGS_PATH())
        except (OSError, ValueError):
            settings = AppSettings()
    if ffmpeg_path is None:
        ffmpeg_path = find_ffmpeg() or Path("ffmpeg.exe")
    return MainWindow(settings=settings, ffmpeg_path=ffmpeg_path)


def main() -> int:
    # 콘솔 없는 실행(pythonw.exe / PyInstaller console=False)에선 sys.stdout·stderr 가
    # None 이라, stderr 에 직접 쓰는 서드파티가 즉사한다. 실측: 자동 누끼 모델 다운로드
    # (rembg→pooch→tqdm 진행률 막대)가 첫 줄을 그리려 sys.stderr.write 를 호출하다
    # AttributeError → 모델 0바이트 정체("0.0/5MB"). 다른 모든 것보다 먼저 None 스트림을
    # 안전한 싱크로 교체한다 (콘솔 있으면 무해).
    from screen_recorder.app.std_streams import ensure_std_streams
    ensure_std_streams()

    from screen_recorder.core.logging_setup import setup_logging
    setup_logging()
    import logging
    import threading
    logging.info("KStudio started")
    # 미처리 예외도 로그에 남도록 — 다음 크래시 시 traceback 가 app.log 에 기록되어
    # 같은 자리에서 디버깅 가능 (Qt event loop 안의 슬롯 예외도 default excepthook 경유).
    def _log_uncaught(exc_type, exc_value, exc_tb):
        logging.error("UNCAUGHT EXCEPTION",
                      exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _log_uncaught

    # sys.excepthook 은 **메인 스레드** 예외만 잡는다. 백그라운드 스레드(캡처/인코더
    # 등)에서 터진 예외는 threading.excepthook 로 가고, 기본 동작은 콘솔(stderr)에만
    # 찍어 app.log 엔 안 남는다 → cmd 창을 닫으면 추적 불가. (2026-06-09 캡처 스레드의
    # 'Invalid Region' ValueError 가 정확히 이 경우라, 사용자가 cmd 를 직접 복사해야
    # 원인이 드러났다.) 스레드 크래시도 app.log 에 남겨 같은 일을 안 겪게 한다.
    def _log_thread_uncaught(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        logging.error("UNCAUGHT THREAD EXCEPTION in %s", name,
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _log_thread_uncaught

    # QtWebEngine 위생(권장) — GL 컨텍스트 공유는 QApplication 생성 *전* 에 켜야 한다.
    # 문서 미리보기(WebEngine)와 영상 GL 표면이 컨텍스트를 공유해 렌더 글리치를 줄인다.
    # (문서 첫 진입 깜빡임의 핵심 fix 는 MainWindow 의 WebEngine pre-warm 이며 이건 별개.)
    from PySide6.QtCore import Qt
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("KStudio")
    # 트레이로 숨겨도 마지막 윈도우 닫힘 신호로 종료되지 않도록.
    # (closeEvent 가 hide() 로 우회하지만, 자동 시작 모드에서는 처음부터 창을
    # 한 번도 보여주지 않으므로 이 보호가 더 중요해진다.)
    app.setQuitOnLastWindowClosed(False)

    # 단일 인스턴스 — 탐색기에서 .md/.kstudio 더블클릭 시 새 KStudio 창이 또 뜨는 대신
    # 이미 실행 중인 인스턴스가 그 파일을 열도록(라이브러리 추가 + 표시) 한다.
    # 무거운 초기화(MainWindow/torch/WebEngine) 전에 검사 → 두 번째 프로세스는 빠르게 종료.
    from screen_recorder.app import single_instance
    _file_args = [
        a for a in sys.argv[1:]
        if a and not a.startswith("-") and Path(a).is_file()
    ]
    if single_instance.try_forward(_file_args):
        return 0  # 이미 실행 중인 인스턴스가 처리 — 이 프로세스는 조용히 종료.
    # 첫 인스턴스: 파이프를 선점(핸들러는 MainWindow 생성 후 연결). 초기화 도중 들어온
    # 두 번째 실행의 메시지는 큐에 쌓였다가 set_handler 에서 flush 된다.
    _si_server = single_instance.SingleInstanceServer(parent=app)
    _si_server.listen()
    from screen_recorder.ui.app_icon import app_icon
    from screen_recorder.ui.theme import apply_theme
    app.setWindowIcon(app_icon())
    # 마지막 사용 모드를 settings 에서 읽어 초기 테마 적용 — 재시작 시 깜빡임 방지.
    # 잘못된 값(파일 손상/구버전)은 "image" 로 폴백.
    settings = _settings_module.load(SETTINGS_PATH())
    initial_palette = settings.preferences.last_mode
    if initial_palette not in ("video", "image", "document"):
        initial_palette = "image"
    apply_theme(app, initial_palette)

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

    # i18n — settings.preferences.language 에 따라 한국어/영어 결정.
    # i18n_en import 시점에 영문 번역 사전이 자동 등록 (모듈 부팅 사이드이펙트).
    from screen_recorder.core import i18n
    from screen_recorder.core import i18n_en  # noqa: F401  — 사전 등록을 위한 import
    if settings.preferences.language in ("ko", "en"):
        i18n.set_language(settings.preferences.language)  # type: ignore[arg-type]

    win = MainWindow(settings=settings, ffmpeg_path=ffmpeg)

    def on_about_to_quit():
        _settings_module.save(win.app_settings, SETTINGS_PATH())
    app.aboutToQuit.connect(on_about_to_quit)

    # 두 번째 실행이 보낸 파일/요청 처리: 그 파일을 열고(라이브러리 추가 + 표시) 창을 앞으로.
    def _on_forwarded(paths):
        for sp in paths:
            p = Path(sp)
            if p.is_file():
                win._open_path(p)
        # 트레이로 숨겼거나 최소화돼 있어도 보이게 + 포그라운드로(win.bring_to_front
        # 안에서 show/raise/activate + Win32 force_foreground 까지 처리).
        win.bring_to_front()
    _si_server.set_handler(_on_forwarded)

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
