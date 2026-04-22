"""시스템 트레이 아이콘."""
from PySide6.QtCore import Signal, QObject
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication


class TrayController(QObject):
    show_main = Signal()
    quit_requested = Signal()
    toggle_record = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray = QSystemTrayIcon(QIcon.fromTheme("media-record"), parent)
        if self.tray.icon().isNull():
            from PySide6.QtWidgets import QStyle
            style = QApplication.instance().style() if QApplication.instance() else None
            if style is not None:
                self.tray.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.tray.setToolTip("Screen Recorder")

        menu = QMenu()
        show_action = QAction("창 보이기", menu); show_action.triggered.connect(self.show_main.emit)
        rec_action = QAction("녹화 시작/정지", menu); rec_action.triggered.connect(self.toggle_record.emit)
        quit_action = QAction("종료", menu); quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(show_action); menu.addAction(rec_action); menu.addSeparator(); menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_main.emit()
