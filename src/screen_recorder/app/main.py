"""QApplication 진입점."""
from __future__ import annotations
import sys

from PySide6.QtWidgets import QApplication

from screen_recorder.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
