"""QApplication 진입점."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.core.settings import AppSettings, load, save
from screen_recorder.ui.main_window import MainWindow


SETTINGS_PATH = Path.home() / "AppData" / "Local" / "ScreenRecorder" / "settings.json"


def main() -> int:
    app = QApplication(sys.argv)

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
