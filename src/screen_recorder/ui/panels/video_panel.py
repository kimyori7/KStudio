"""영상 설정 패널."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QSpinBox, QSlider, QHBoxLayout,
)

from ...core.settings import VideoSettings


class VideoPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: VideoSettings):
        super().__init__()
        self.settings = settings
        form = QFormLayout(self)

        self.container = QComboBox()
        for v in ("mp4", "mkv", "webm"):
            self.container.addItem(v, v)
        self.container.setCurrentText(settings.container)
        form.addRow("컨테이너:", self.container)

        self.codec = QComboBox()
        for v, label in [("h264", "H.264"), ("h265", "H.265"), ("vp9", "VP9")]:
            self.codec.addItem(label, v)
        idx = self.codec.findData(settings.codec)
        self.codec.setCurrentIndex(max(idx, 0))
        form.addRow("코덱:", self.codec)

        self.fps = QComboBox()
        for v in (30, 60):
            self.fps.addItem(str(v), v)
        self.fps.setCurrentText(str(settings.fps))
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

        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 50000)
        self.bitrate.setSingleStep(500)
        self.bitrate.setSuffix(" kbps")
        self.bitrate.setValue(settings.bitrate_kbps)
        form.addRow("비트레이트:", self.bitrate)

        for w in (self.container, self.codec, self.fps):
            w.currentIndexChanged.connect(self._sync)
        self.bitrate.valueChanged.connect(self._sync)
        self.scale_spin.valueChanged.connect(self._sync)

    def _sync(self):
        self.settings.container = self.container.currentData()
        self.settings.codec = self.codec.currentData()
        self.settings.fps = int(self.fps.currentData())
        self.settings.scale_percent = self.scale_spin.value()
        self.settings.bitrate_kbps = self.bitrate.value()
        self.settings_changed.emit()
