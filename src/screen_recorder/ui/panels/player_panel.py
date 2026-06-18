"""영상 플레이어 설정 패널 — 건너뛰기 구간 + 오디오 출력 장치."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QSpinBox, QComboBox, QGroupBox, QVBoxLayout,
)

from ...core.settings import PlayerSettings
from ..video.audio_devices_qt import list_outputs
from ..video.audio_device_list import disambiguate_labels, resolve_current_id


class PlayerPanel(QWidget):
    settings_changed = Signal()
    audio_device_changed = Signal(str)   # 선택된 출력 장치 id ("" = 시스템 기본 따라가기)

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

        # ---- 오디오 출력 장치 (2026-06-17) ----
        # "이 앱만 무음" 대응: Qt 가 모니터 HDMI 를 기본으로 잡는 환경에서 실제 스피커/
        # 헤드폰을 직접 고를 수 있게. 맨 위 "시스템 기본 따라가기" + 장치 목록. 선택은
        # 전역 PlayerSettings 에 저장되고(종료 시 영속), main_window 가 열린 영상 탭의
        # player 에 즉시 적용한다. 장치 목록이 바뀌면(플러그) 콤보를 다시 채운다.
        audio_box = QGroupBox("소리 출력 장치")
        audio_form = QFormLayout(audio_box)
        self._populating = False
        self.audio_device_combo = QComboBox()
        self.audio_device_combo.setToolTip(
            "소리가 안 나면 여기서 실제로 듣는 스피커/헤드폰을 고르세요.\n"
            "'시스템 기본 따라가기'는 Windows 기본 장치를 따라갑니다.")
        self.audio_device_combo.currentIndexChanged.connect(self._on_device_index_changed)
        audio_form.addRow("출력 장치", self.audio_device_combo)
        root.addWidget(audio_box)

        root.addStretch(1)

        # 장치 목록 변경(플러그/언플러그) 추종 — 패널이 열려 있는 동안 갱신.
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._populate_devices)
        self._populate_devices()

    # ---------- 오디오 장치 ----------
    def _populate_devices(self) -> None:
        """현재 시스템 출력 장치로 콤보를 채운다 (저장값 선택 반영). populate 중 시그널 억제.

        같은 이름 장치(모니터 2대 등)는 (2),(3) 으로 구분. 저장 장치가 사라졌으면
        '기본 따라가기'로 표시(복귀 시 자동 재매칭은 player 가 담당)."""
        raw = list_outputs()
        labeled = disambiguate_labels(raw)
        current = resolve_current_id(
            self._settings.audio_output_device, [i for i, _ in raw])
        self._populating = True
        try:
            self.audio_device_combo.clear()
            self.audio_device_combo.addItem("시스템 기본 따라가기", "")
            for dev_id, label in labeled:
                self.audio_device_combo.addItem(label, dev_id)
            idx = self.audio_device_combo.findData(current) if current else 0
            self.audio_device_combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._populating = False

    def _on_device_index_changed(self, _idx: int) -> None:
        if self._populating:
            return
        dev_id = self.audio_device_combo.currentData() or ""
        self._settings.audio_output_device = dev_id
        self.audio_device_changed.emit(dev_id)
        self.settings_changed.emit()

    # ---------- 건너뛰기 ----------
    def _on_skip_changed(self, v: int) -> None:
        self._settings.skip_seconds = v
        self.settings_changed.emit()

    def _on_medium_changed(self, v: int) -> None:
        self._settings.skip_medium_seconds = v
        self.settings_changed.emit()

    def _on_large_changed(self, v: int) -> None:
        self._settings.skip_large_seconds = v
        self.settings_changed.emit()
