"""환경설정 패널."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QComboBox, QLabel

from ...core.settings import PreferencesSettings
from ...core.i18n import tr


class PreferencesPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: PreferencesSettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.autostart = QCheckBox(tr("Windows 시작 시 자동 실행"))
        self.autostart.setChecked(settings.autostart)
        form.addRow(self.autostart)

        self.tray = QCheckBox(tr("녹화 중 메인 창을 트레이로 숨기기"))
        self.tray.setChecked(settings.minimize_to_tray)
        form.addRow(self.tray)

        self.mini_control = QCheckBox(tr("녹화 중 미니 컨트롤(⏹ ⏸) 표시"))
        self.mini_control.setChecked(settings.use_mini_control)
        form.addRow(self.mini_control)

        self.lang = QComboBox()
        self.lang.addItem(tr("한국어"), "ko")
        self.lang.addItem(tr("영어"), "en")
        idx = self.lang.findData(settings.language)
        self.lang.setCurrentIndex(max(idx, 0))
        form.addRow(tr("언어") + ":", self.lang)

        # 즉시 반영이 아니라 재시작 후 적용 — UI 모든 위젯에 retranslate hook 을
        # 달지 않아도 되어 코드가 가벼워짐. 사용자에겐 한 줄 안내.
        hint = QLabel(tr("언어 변경은 앱 재시작 후 적용됩니다."))
        hint.setStyleSheet("color: #888; font-size: 9pt;")
        form.addRow("", hint)

        self.autostart.toggled.connect(self._sync)
        self.tray.toggled.connect(self._sync)
        self.mini_control.toggled.connect(self._sync)
        self.lang.currentIndexChanged.connect(self._sync)

    def _sync(self):
        self.settings.autostart = self.autostart.isChecked()
        self.settings.minimize_to_tray = self.tray.isChecked()
        self.settings.use_mini_control = self.mini_control.isChecked()
        self.settings.language = self.lang.currentData()
        self.settings_changed.emit()
