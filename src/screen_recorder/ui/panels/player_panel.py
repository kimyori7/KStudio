"""영상 플레이어 설정 패널 — 건너뛰기 구간들."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QSpinBox, QGroupBox, QVBoxLayout

from ...core.settings import PlayerSettings


class PlayerPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: PlayerSettings) -> None:
        super().__init__()
        self._settings = settings

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        box = QGroupBox("⏱ 건너뛰기 구간")
        form = QFormLayout(box)

        self.skip_spin = QSpinBox()
        self.skip_spin.setRange(1, 600)
        self.skip_spin.setSuffix(" 초")
        self.skip_spin.setValue(settings.skip_seconds)
        self.skip_spin.valueChanged.connect(self._on_skip_changed)
        form.addRow("← / → 키", self.skip_spin)

        self.medium_spin = QSpinBox()
        self.medium_spin.setRange(1, 600)
        self.medium_spin.setSuffix(" 초")
        self.medium_spin.setValue(settings.skip_medium_seconds)
        self.medium_spin.valueChanged.connect(self._on_medium_changed)
        form.addRow("Shift + ← / →", self.medium_spin)

        self.large_spin = QSpinBox()
        self.large_spin.setRange(1, 600)
        self.large_spin.setSuffix(" 초")
        self.large_spin.setValue(settings.skip_large_seconds)
        self.large_spin.valueChanged.connect(self._on_large_changed)
        form.addRow("Ctrl + ← / →", self.large_spin)

        root.addWidget(box)
        root.addStretch(1)

    def _on_skip_changed(self, v: int) -> None:
        self._settings.skip_seconds = v
        self.settings_changed.emit()

    def _on_medium_changed(self, v: int) -> None:
        self._settings.skip_medium_seconds = v
        self.settings_changed.emit()

    def _on_large_changed(self, v: int) -> None:
        self._settings.skip_large_seconds = v
        self.settings_changed.emit()
