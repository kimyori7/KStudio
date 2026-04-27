"""QApplication 진입점."""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Qt의 DPI awareness 경고 숨김 (이미 프로세스 DPI가 설정된 경우 Qt가 재설정 못해서 생기는 무해한 경고)
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window=false")

from PySide6.QtWidgets import QApplication, QMessageBox

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.core.settings import AppSettings, load, save
from screen_recorder.ui.main_window import MainWindow


SETTINGS_PATH = Path.home() / "AppData" / "Local" / "KStudio" / "settings.json"


def main() -> int:
    from screen_recorder.core.logging_setup import setup_logging
    setup_logging()
    import logging
    logging.info("KStudio started")

    app = QApplication(sys.argv)
    app.setApplicationName("KStudio")
    from screen_recorder.ui.app_icon import app_icon
    from screen_recorder.ui.theme import apply_theme
    app.setWindowIcon(app_icon())
    apply_theme(app)

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

    win = MainWindow(settings=settings, ffmpeg_path=ffmpeg)

    def on_about_to_quit():
        save(win.app_settings, SETTINGS_PATH)
    app.aboutToQuit.connect(on_about_to_quit)

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
