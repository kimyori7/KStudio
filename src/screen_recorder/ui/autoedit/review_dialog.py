"""AutoEditReviewDialog — 4 카드 + 슬라이더 라이브 + '적용'.

Phase 1 = silence 카드만. caption/scene/bpm 카드는 후속 Phase 에서 추가.
"""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from ...autoedit.result import AutoEditResult
from ...autoedit.presets import AutoEditSettings, default_settings
from ...autoedit.filter import apply_thresholds


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
WHISPER_MODEL_LABELS = {
    "tiny": "tiny (~75MB, 가장 빠름, 정확도 낮음)",
    "base": "base (~150MB, 빠름)",
    "small": "small (~500MB, 보통)",
    "medium": "medium (~1.5GB, 느림, 정확)",
    "large-v3": "large-v3 (~3GB, 매우 느림, 최고 정확)",
}


def _is_model_downloaded(model_size: str) -> bool:
    """HuggingFace 캐시에 해당 모델이 받아져 있는지 — 라벨에 '(다운로드 필요)' 표시용."""
    cache = Path.home() / ".cache" / "huggingface" / "hub" / f"models--Systran--faster-whisper-{model_size}"
    return cache.exists()


def _is_scenedetect_available() -> bool:
    try:
        import scenedetect  # noqa
        return True
    except ImportError:
        return False


def _is_librosa_available() -> bool:
    try:
        import librosa  # noqa
        return True
    except ImportError:
        return False


def _make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(f)
    lbl = QLabel(f"<b>{title}</b>")
    lay.addWidget(lbl)
    return f, lay


class AutoEditReviewDialog(QDialog):
    # 사용자가 자막 카드의 '재분석' 누름 → 다이얼로그 닫고 새 모델로 다시 분석.
    reanalyze_requested = Signal(str)   # new_model

    def __init__(
        self,
        raw: AutoEditResult,
        parent: QWidget | None = None,
        *,
        current_whisper_model: str = "large-v3",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("자동 편집 결과 미리보기")
        self.setModal(True)
        self._raw = raw
        self._current_whisper_model = current_whisper_model
        self._settings = default_settings()

        # debounce: 슬라이더 드래그 중 100ms 마다만 재필터.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(100)
        self._filter_timer.timeout.connect(self._refresh_counts)

        root = QVBoxLayout(self)
        root.addWidget(self._build_silence_card())
        root.addWidget(self._build_caption_card())
        root.addWidget(self._build_scene_card())
        root.addWidget(self._build_bpm_card())

        # 적용 / 취소 / 기본값.
        btn_row = QHBoxLayout()
        self._total_label = QLabel("적용 예정: 0개")
        btn_row.addWidget(self._total_label)
        btn_row.addStretch(1)
        self._reset_btn = QPushButton("기본값 복원")
        self._reset_btn.clicked.connect(self._reset_defaults)
        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn = QPushButton("적용")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._reset_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._apply_btn)
        root.addLayout(btn_row)

        self._refresh_counts()

    def _build_silence_card(self) -> QFrame:
        card, lay = _make_card("🤐 무음컷")
        row1 = QHBoxLayout()
        self._silence_check = QCheckBox("사용")
        self._silence_check.setChecked(self._settings.silence_enabled)
        self._silence_check.toggled.connect(self._on_silence_toggle)
        self._silence_count = QLabel("0개 컷")
        row1.addWidget(self._silence_check)
        row1.addStretch(1)
        row1.addWidget(self._silence_count)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("무음 최소 길이"))
        self._silence_slider = QSlider(Qt.Horizontal)
        self._silence_slider.setRange(200, 3000)
        self._silence_slider.setValue(self._settings.silence_min_ms)
        self._silence_slider.setSingleStep(100)
        self._silence_slider.valueChanged.connect(self._on_silence_slider)
        self._silence_value = QLabel(f"{self._settings.silence_min_ms / 1000:.1f}초")
        row2.addWidget(self._silence_slider, stretch=1)
        row2.addWidget(self._silence_value)
        lay.addLayout(row2)
        return card

    def _build_caption_card(self) -> QFrame:
        card, lay = _make_card("💬 자막 (Whisper)")
        row1 = QHBoxLayout()
        self._caption_check = QCheckBox("사용")
        self._caption_check.setChecked(self._settings.caption_enabled)
        self._caption_check.toggled.connect(self._on_caption_toggle)
        self._caption_count = QLabel("0개 자막")
        row1.addWidget(self._caption_check)
        row1.addStretch(1)
        row1.addWidget(self._caption_count)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("한 줄 최대 글자"))
        self._caption_slider = QSlider(Qt.Horizontal)
        self._caption_slider.setRange(10, 80)
        self._caption_slider.setValue(self._settings.caption_max_chars)
        self._caption_slider.valueChanged.connect(self._on_caption_slider)
        self._caption_val = QLabel(f"{self._settings.caption_max_chars}자")
        row2.addWidget(self._caption_slider, stretch=1)
        row2.addWidget(self._caption_val)
        lay.addLayout(row2)

        # Whisper 모델 선택 + 재분석 (정확도 부족할 때 더 큰 모델로).
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Whisper 모델"))
        self._model_combo = QComboBox()
        for m in WHISPER_MODELS:
            label = WHISPER_MODEL_LABELS[m]
            if not _is_model_downloaded(m):
                label += "  ⬇ 다운로드 필요"
            self._model_combo.addItem(label, userData=m)
        # 현재 모델 선택.
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == self._current_whisper_model:
                self._model_combo.setCurrentIndex(i)
                break
        row3.addWidget(self._model_combo, stretch=1)
        self._reanalyze_btn = QPushButton("재분석")
        self._reanalyze_btn.setToolTip("선택한 모델로 다시 분석 — 다운로드 안 되어 있으면 자동 받음")
        self._reanalyze_btn.clicked.connect(self._on_reanalyze_clicked)
        # 현재 모델 그대로면 비활성 (의미 없는 재분석 방지).
        self._model_combo.currentIndexChanged.connect(self._refresh_reanalyze_state)
        self._refresh_reanalyze_state()
        row3.addWidget(self._reanalyze_btn)
        lay.addLayout(row3)
        return card

    def _refresh_reanalyze_state(self) -> None:
        selected = self._model_combo.currentData()
        self._reanalyze_btn.setEnabled(selected != self._current_whisper_model)

    def _on_reanalyze_clicked(self) -> None:
        new_model = self._model_combo.currentData()
        # 다이얼로그 닫고 시그널 emit — VideoTab 이 받아 settings 갱신 + _start_autoedit.
        self.reject()
        self.reanalyze_requested.emit(new_model)

    def model_combo(self) -> QComboBox: return self._model_combo
    def reanalyze_button(self) -> QPushButton: return self._reanalyze_btn

    def _build_scene_card(self) -> QFrame:
        card, lay = _make_card("🎬 씬 감지")
        row1 = QHBoxLayout()
        self._scene_check = QCheckBox("사용")
        self._scene_check.setChecked(self._settings.scene_enabled)
        self._scene_check.toggled.connect(self._on_scene_toggle)
        self._scene_count = QLabel("0개 줌")
        row1.addWidget(self._scene_check)
        row1.addStretch(1)
        row1.addWidget(self._scene_count)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("민감도"))
        self._scene_slider = QSlider(Qt.Horizontal)
        self._scene_slider.setRange(10, 60)
        self._scene_slider.setValue(self._settings.scene_sensitivity)
        self._scene_slider.valueChanged.connect(self._on_scene_slider)
        self._scene_val = QLabel(str(self._settings.scene_sensitivity))
        row2.addWidget(self._scene_slider, stretch=1)
        row2.addWidget(self._scene_val)
        lay.addLayout(row2)

        # 의존성 누락 시 dim.
        if not _is_scenedetect_available():
            self._scene_check.setEnabled(False)
            self._scene_check.setChecked(False)
            self._scene_check.setToolTip("씬감지를 쓰려면: pip install scenedetect")
            self._scene_slider.setEnabled(False)
            self._settings.scene_enabled = False
        return card

    def _on_scene_toggle(self, c: bool) -> None:
        self._settings.scene_enabled = c
        self._scene_slider.setEnabled(c)
        self._filter_timer.start()

    def _on_scene_slider(self, v: int) -> None:
        self._settings.scene_sensitivity = v
        self._scene_val.setText(str(v))
        self._filter_timer.start()

    def scene_checkbox(self) -> QCheckBox: return self._scene_check
    def scene_count_label(self) -> QLabel: return self._scene_count

    def _build_bpm_card(self) -> QFrame:
        card, lay = _make_card("🥁 BPM 비트 sync")
        row1 = QHBoxLayout()
        self._bpm_check = QCheckBox("사용 (음악 영상에 권장)")
        self._bpm_check.setChecked(self._settings.bpm_enabled)
        self._bpm_check.toggled.connect(self._on_bpm_toggle)
        row1.addWidget(self._bpm_check)
        row1.addStretch(1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("신뢰도"))
        self._bpm_slider = QSlider(Qt.Horizontal)
        self._bpm_slider.setRange(40, 90)   # 0.4 ~ 0.9 (slider int → /100)
        self._bpm_slider.setValue(int(self._settings.bpm_confidence * 100))
        self._bpm_slider.valueChanged.connect(self._on_bpm_slider)
        self._bpm_val = QLabel(f"{self._settings.bpm_confidence:.2f}")
        self._bpm_slider.setEnabled(self._settings.bpm_enabled)
        row2.addWidget(self._bpm_slider, stretch=1)
        row2.addWidget(self._bpm_val)
        lay.addLayout(row2)

        if not _is_librosa_available():
            self._bpm_check.setEnabled(False)
            self._bpm_check.setChecked(False)
            self._bpm_check.setToolTip("BPM 분석을 쓰려면: pip install librosa")
            self._bpm_slider.setEnabled(False)
            self._settings.bpm_enabled = False
        return card

    def _on_bpm_toggle(self, c: bool) -> None:
        self._settings.bpm_enabled = c
        self._bpm_slider.setEnabled(c)
        self._filter_timer.start()

    def _on_bpm_slider(self, v: int) -> None:
        self._settings.bpm_confidence = v / 100.0
        self._bpm_val.setText(f"{self._settings.bpm_confidence:.2f}")
        self._filter_timer.start()

    def bpm_checkbox(self) -> QCheckBox: return self._bpm_check

    def _on_caption_toggle(self, c: bool) -> None:
        self._settings.caption_enabled = c
        self._caption_slider.setEnabled(c)
        self._filter_timer.start()

    def _on_caption_slider(self, v: int) -> None:
        self._settings.caption_max_chars = v
        self._caption_val.setText(f"{v}자")
        self._filter_timer.start()

    def caption_count_label(self) -> QLabel: return self._caption_count

    def _on_silence_toggle(self, checked: bool) -> None:
        self._settings.silence_enabled = checked
        self._silence_slider.setEnabled(checked)
        self._filter_timer.start()

    def _on_silence_slider(self, v: int) -> None:
        self._settings.silence_min_ms = v
        self._silence_value.setText(f"{v / 1000:.1f}초")
        self._filter_timer.start()

    def _reset_defaults(self) -> None:
        self._settings = default_settings()
        self._silence_check.setChecked(self._settings.silence_enabled)
        self._silence_slider.setValue(self._settings.silence_min_ms)
        self._caption_check.setChecked(self._settings.caption_enabled)
        self._caption_slider.setValue(self._settings.caption_max_chars)
        # scene card 는 의존성 없으면 OFF 유지 — 강제 활성화 X.
        if _is_scenedetect_available():
            self._scene_check.setChecked(self._settings.scene_enabled)
        self._scene_slider.setValue(self._settings.scene_sensitivity)
        if _is_librosa_available():
            self._bpm_check.setChecked(self._settings.bpm_enabled)
        self._bpm_slider.setValue(int(self._settings.bpm_confidence * 100))
        self._filter_timer.stop()
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        effects = apply_thresholds(self._raw, self._settings)
        cuts = [e for e in effects if e.type == "cut"]
        caps = [e for e in effects if e.type == "caption"]
        zooms = [e for e in effects if e.type == "zoom"]
        self._silence_count.setText(f"{len(cuts)}개 컷")
        self._caption_count.setText(f"{len(caps)}개 자막")
        self._scene_count.setText(f"{len(zooms)}개 줌")
        self._total_label.setText(f"적용 예정: {len(effects)}개")
        self._apply_btn.setEnabled(len(effects) > 0)

    def _flush_filter_now(self) -> None:
        """테스트용 — debounce timer 즉시 trigger."""
        self._filter_timer.stop()
        self._refresh_counts()

    def compute_effects(self) -> list:
        return apply_thresholds(self._raw, self._settings)

    # 테스트 접근용.
    def silence_checkbox(self) -> QCheckBox: return self._silence_check
    def silence_slider(self) -> QSlider: return self._silence_slider
    def silence_count_label(self) -> QLabel: return self._silence_count
