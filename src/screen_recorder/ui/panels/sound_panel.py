"""사운드 설정 패널."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox

from ...core.settings import SoundSettings


class SoundPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: SoundSettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.enabled = QCheckBox("시스템 오디오 녹음")
        self.enabled.setChecked(settings.system_audio_enabled)
        form.addRow(self.enabled)

        self.codec = QComboBox()
        for v in ("aac", "mp3"):
            self.codec.addItem(v.upper(), v)
        self.codec.setCurrentText(settings.codec.upper())
        form.addRow("코덱:", self.codec)

        self.bitrate = QSpinBox()
        self.bitrate.setRange(64, 320)
        self.bitrate.setSingleStep(32)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setValue(settings.bitrate_kbps)
        form.addRow("비트레이트:", self.bitrate)

        self.enabled.toggled.connect(self._sync)
        self.codec.currentIndexChanged.connect(self._sync)
        self.bitrate.valueChanged.connect(self._sync)

    def _sync(self):
        self.settings.system_audio_enabled = self.enabled.isChecked()
        self.settings.codec = self.codec.currentData()
        self.settings.bitrate_kbps = self.bitrate.value()
        self.settings_changed.emit()
