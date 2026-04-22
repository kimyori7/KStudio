"""GIF 설정 패널."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QSlider, QComboBox, QHBoxLayout,
)

from ...core.settings import GifSettings


class GifPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: GifSettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.fps = QSpinBox()
        self.fps.setRange(1, 30)
        self.fps.setSuffix(" fps")
        self.fps.setValue(settings.fps)
        form.addRow("FPS:", self.fps)

        scale_row = QWidget()
        scale_layout = QHBoxLayout(scale_row)
        scale_layout.setContentsMargins(0, 0, 0, 0)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(10, 100)
        self.scale_slider.setValue(settings.scale_percent)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(10, 100)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(settings.scale_percent)
        self.scale_slider.valueChanged.connect(self.scale_spin.setValue)
        self.scale_spin.valueChanged.connect(self.scale_slider.setValue)
        scale_layout.addWidget(self.scale_slider, stretch=1)
        scale_layout.addWidget(self.scale_spin)
        form.addRow("출력 스케일:", scale_row)

        self.colors = QComboBox()
        for v in (64, 128, 256):
            self.colors.addItem(str(v), v)
        self.colors.setCurrentText(str(settings.colors))
        form.addRow("색상 수:", self.colors)

        self.fps.valueChanged.connect(self._sync)
        self.scale_spin.valueChanged.connect(self._sync)
        self.colors.currentIndexChanged.connect(self._sync)

    def _sync(self):
        self.settings.fps = self.fps.value()
        self.settings.scale_percent = self.scale_spin.value()
        self.settings.colors = int(self.colors.currentData())
        self.settings_changed.emit()
