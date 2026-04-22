"""환경설정 패널."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QComboBox

from ...core.settings import PreferencesSettings


class PreferencesPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: PreferencesSettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.autostart = QCheckBox("Windows 시작 시 자동 실행")
        self.autostart.setChecked(settings.autostart)
        form.addRow(self.autostart)

        self.tray = QCheckBox("최소화 시 트레이로")
        self.tray.setChecked(settings.minimize_to_tray)
        form.addRow(self.tray)

        self.lang = QComboBox()
        self.lang.addItem("한국어", "ko")
        idx = self.lang.findData(settings.language)
        self.lang.setCurrentIndex(max(idx, 0))
        form.addRow("언어:", self.lang)

        self.autostart.toggled.connect(self._sync)
        self.tray.toggled.connect(self._sync)
        self.lang.currentIndexChanged.connect(self._sync)

    def _sync(self):
        self.settings.autostart = self.autostart.isChecked()
        self.settings.minimize_to_tray = self.tray.isChecked()
        self.settings.language = self.lang.currentData()
        self.settings_changed.emit()
