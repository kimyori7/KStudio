"""영상 설정 패널 — 영상 / 사운드 / GIF 3개 섹션을 QGroupBox로 묶어 표시."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QSpinBox, QSlider, QHBoxLayout, QCheckBox,
    QGroupBox, QVBoxLayout,
)

from ...core.settings import VideoSettings, GifSettings, SoundSettings


def _make_scale_row(initial: int) -> tuple[QWidget, QSlider, QSpinBox]:
    """슬라이더 + 스핀박스 쌍 (10..100 %)을 한 줄로 만든다."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(10, 100)
    slider.setValue(initial)
    spin = QSpinBox()
    spin.setRange(10, 100)
    spin.setSuffix(" %")
    spin.setValue(initial)
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)
    layout.addWidget(slider, stretch=1)
    layout.addWidget(spin)
    return row, slider, spin


class VideoPanel(QWidget):
    settings_changed = Signal()

    def __init__(
        self,
        video: VideoSettings,
        gif: GifSettings,
        sound: SoundSettings,
    ):
        super().__init__()
        self.video = video
        self.gif = gif
        self.sound = sound

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_video_box())
        root.addWidget(self._build_sound_box())
        root.addWidget(self._build_gif_box())
        root.addStretch(1)

    # ---------- 영상 ----------

    def _build_video_box(self) -> QGroupBox:
        box = QGroupBox("🎬 영상")
        form = QFormLayout(box)

        self.v_container = QComboBox()
        for v in ("mp4", "mkv", "webm"):
            self.v_container.addItem(v, v)
        self.v_container.setCurrentText(self.video.container)
        form.addRow("컨테이너:", self.v_container)

        self.v_codec = QComboBox()
        for v, label in [("h264", "H.264"), ("h265", "H.265"), ("vp9", "VP9")]:
            self.v_codec.addItem(label, v)
        idx = self.v_codec.findData(self.video.codec)
        self.v_codec.setCurrentIndex(max(idx, 0))
        form.addRow("코덱:", self.v_codec)

        self.v_fps = QComboBox()
        for v in (30, 60):
            self.v_fps.addItem(str(v), v)
        self.v_fps.setCurrentText(str(self.video.fps))
        form.addRow("FPS:", self.v_fps)

        scale_row, self.v_scale_slider, self.v_scale_spin = _make_scale_row(self.video.scale_percent)
        form.addRow("출력 스케일:", scale_row)

        self.v_bitrate = QSpinBox()
        self.v_bitrate.setRange(500, 50000)
        self.v_bitrate.setSingleStep(500)
        self.v_bitrate.setSuffix(" kbps")
        self.v_bitrate.setValue(self.video.bitrate_kbps)
        form.addRow("비트레이트:", self.v_bitrate)

        for w in (self.v_container, self.v_codec, self.v_fps):
            w.currentIndexChanged.connect(self._sync)
        self.v_bitrate.valueChanged.connect(self._sync)
        self.v_scale_spin.valueChanged.connect(self._sync)

        return box

    # ---------- GIF ----------

    def _build_gif_box(self) -> QGroupBox:
        box = QGroupBox("🎞 GIF")
        form = QFormLayout(box)

        self.g_fps = QSpinBox()
        self.g_fps.setRange(1, 30)
        self.g_fps.setSuffix(" fps")
        self.g_fps.setValue(self.gif.fps)
        form.addRow("FPS:", self.g_fps)

        scale_row, self.g_scale_slider, self.g_scale_spin = _make_scale_row(self.gif.scale_percent)
        form.addRow("출력 스케일:", scale_row)

        self.g_colors = QComboBox()
        for v in (64, 128, 256):
            self.g_colors.addItem(str(v), v)
        self.g_colors.setCurrentText(str(self.gif.colors))
        form.addRow("색상 수:", self.g_colors)

        self.g_fps.valueChanged.connect(self._sync)
        self.g_scale_spin.valueChanged.connect(self._sync)
        self.g_colors.currentIndexChanged.connect(self._sync)

        return box

    # ---------- 사운드 ----------

    def _build_sound_box(self) -> QGroupBox:
        box = QGroupBox("🔊 사운드")
        form = QFormLayout(box)

        self.s_enabled = QCheckBox("시스템 오디오 녹음")
        self.s_enabled.setChecked(self.sound.system_audio_enabled)
        form.addRow(self.s_enabled)

        self.s_codec = QComboBox()
        for v in ("aac", "mp3"):
            self.s_codec.addItem(v.upper(), v)
        self.s_codec.setCurrentText(self.sound.codec.upper())
        form.addRow("코덱:", self.s_codec)

        self.s_bitrate = QSpinBox()
        self.s_bitrate.setRange(64, 320)
        self.s_bitrate.setSingleStep(32)
        self.s_bitrate.setSuffix(" kbps")
        self.s_bitrate.setValue(self.sound.bitrate_kbps)
        form.addRow("비트레이트:", self.s_bitrate)

        self.s_enabled.toggled.connect(self._sync)
        self.s_codec.currentIndexChanged.connect(self._sync)
        self.s_bitrate.valueChanged.connect(self._sync)

        return box

    # ---------- 동기화 ----------

    def _sync(self) -> None:
        self.video.container = self.v_container.currentData()
        self.video.codec = self.v_codec.currentData()
        self.video.fps = int(self.v_fps.currentData())
        self.video.scale_percent = self.v_scale_spin.value()
        self.video.bitrate_kbps = self.v_bitrate.value()

        self.gif.fps = self.g_fps.value()
        self.gif.scale_percent = self.g_scale_spin.value()
        self.gif.colors = int(self.g_colors.currentData())

        self.sound.system_audio_enabled = self.s_enabled.isChecked()
        self.sound.codec = self.s_codec.currentData()
        self.sound.bitrate_kbps = self.s_bitrate.value()

        self.settings_changed.emit()
