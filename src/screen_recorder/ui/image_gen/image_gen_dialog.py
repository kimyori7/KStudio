"""ImageGenDialog — 비모달 별창 형태 이미지 생성 패널.

지원 모드 (2026-05-27):
- **Text-to-Image**: 프롬프트 → 이미지.
- **Image-to-Image**: 원본 이미지 + 프롬프트 → 변환 이미지 (strength 슬라이더).

모델 카탈로그:
- 품질순 정렬 (FLUX-dev > SD 3.5 Large > SD 3.5 Medium > SDXL 1.0 > PixArt-Sigma).
- 미설치 모델 선택 시 "다운로드" 버튼 활성, 생성 버튼 비활성.
- 다운로드는 기존 `ModelDownloadWindow` + `ModelDownloadJob` 재사용.

진입점:
- 도구 팔레트 "이미지 생성" 액션
- 창 메뉴 "이미지 생성" (Ctrl+Shift+G)

생성 흐름:
- 모델 선택 → 미설치 시 다운로드 → ImageGenRuntime.set_model() → generate() (t2i/i2i 모드)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...image_gen import ImageGenRuntime
from ...image_gen.model_catalog import (
    by_id,
    estimated_size_bytes,
    i2i_models,
    ImageGenModelEntry,
    t2i_models,
)
from ..model_download_window import ModelDownloadWindow

_log = logging.getLogger(__name__)


# HF 캐시에 모델이 다운로드 됐는지 사전 검사 — agent/models/downloader 의 _cache_dir_for_repo
# 와 같은 변환 규칙. 새 의존성 추가 안 하려고 인라인.
def _is_model_cached(repo_id: str, min_size_gb: float = 4.0) -> bool:
    try:
        from huggingface_hub import constants
        dir_name = "models--" + repo_id.replace("/", "--")
        d = Path(constants.HF_HUB_CACHE) / dir_name / "snapshots"
        if not d.exists():
            return False
        total = 0
        for f in d.rglob("*"):
            if f.is_file() and not f.name.endswith(".incomplete"):
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        return total >= int(min_size_gb * 1024**3)
    except Exception:
        return False


class _ReadyPanel(QWidget):
    """모드 + 모델 picker + (옵션) reference 이미지 + 프롬프트 + 결과.

    "ready" 라는 이름은 PixArt 단일 시절 잔재 — 이제는 "미설치 모델 선택 시" 도
    이 패널 안에서 처리 (다운로드 버튼).
    """

    generate_requested = Signal(str, dict)         # prompt, params (i2i 정보 포함)
    cancel_requested = Signal()
    open_in_editor_requested = Signal(str)
    save_as_requested = Signal(str)
    add_to_video_requested = Signal(str)
    auto_translate_toggled = Signal(bool)
    model_changed = Signal(str)                    # 새 model_id
    download_requested = Signal(str)               # 다운로드할 model_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_image_path: Optional[str] = None
        self._recent_paths: list[str] = []
        self._reference_path: Optional[Path] = None
        self._current_mode: str = "t2i"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ---- 모드 라디오 (t2i / i2i) ----
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("모드:"))
        self.t2i_radio = QRadioButton("텍스트 → 이미지")
        self.t2i_radio.setChecked(True)
        self.i2i_radio = QRadioButton("이미지 → 이미지")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.t2i_radio, 0)
        self._mode_group.addButton(self.i2i_radio, 1)
        self.t2i_radio.toggled.connect(self._on_mode_toggled)
        mode_row.addWidget(self.t2i_radio)
        mode_row.addWidget(self.i2i_radio)
        mode_row.addStretch(1)
        outer.addLayout(mode_row)

        # ---- 모델 선택 picker ----
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("모델:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(260)
        self.model_combo.currentIndexChanged.connect(self._on_model_index_changed)
        model_row.addWidget(self.model_combo, stretch=1)
        self.download_btn = QPushButton("다운로드")
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.download_btn.setVisible(False)
        model_row.addWidget(self.download_btn)
        outer.addLayout(model_row)

        self.model_info_label = QLabel("")
        self.model_info_label.setWordWrap(True)
        self.model_info_label.setStyleSheet(
            "color: #9CA3AF; font-size: 11px; padding: 2px 4px;"
        )
        outer.addWidget(self.model_info_label)

        # ---- i2i 원본 이미지 + strength (i2i 모드일 때만 표시) ----
        self.i2i_group = QGroupBox("원본 이미지 (Image-to-Image)")
        i2i_layout = QVBoxLayout(self.i2i_group)
        i2i_layout.setSpacing(6)

        ref_row = QHBoxLayout()
        self.ref_path_label = QLabel("(선택된 이미지 없음)")
        self.ref_path_label.setStyleSheet("color: #6B7280; font-size: 11px;")
        ref_row.addWidget(self.ref_path_label, stretch=1)
        self.ref_browse_btn = QPushButton("이미지 선택…")
        self.ref_browse_btn.clicked.connect(self._on_browse_reference)
        ref_row.addWidget(self.ref_browse_btn)
        i2i_layout.addLayout(ref_row)

        self.ref_preview = QLabel()
        self.ref_preview.setAlignment(Qt.AlignCenter)
        self.ref_preview.setFixedHeight(120)
        self.ref_preview.setStyleSheet(
            "border: 1px dashed #4B5563; background: #1F2630; color: #6B7280;"
        )
        self.ref_preview.setText("(원본 이미지 미리보기)")
        i2i_layout.addWidget(self.ref_preview)

        strength_row = QHBoxLayout()
        strength_row.addWidget(QLabel("Strength:"))
        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(10, 95)     # 0.10 ~ 0.95
        self.strength_slider.setValue(70)         # 기본 0.70
        self.strength_slider.valueChanged.connect(self._on_strength_changed)
        strength_row.addWidget(self.strength_slider, stretch=1)
        self.strength_label = QLabel("0.70")
        self.strength_label.setFixedWidth(40)
        strength_row.addWidget(self.strength_label)
        i2i_layout.addLayout(strength_row)
        strength_hint = QLabel("낮을수록 원본 유지 · 높을수록 새 이미지")
        strength_hint.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        i2i_layout.addWidget(strength_hint)

        self.i2i_group.setVisible(False)
        outer.addWidget(self.i2i_group)

        # ---- 구분선 ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #374151;")
        outer.addWidget(sep)

        # ---- 프롬프트 + 번역 ----
        outer.addWidget(QLabel("프롬프트 (한국어 OK — 자동으로 영어로 번역):"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "예: 노을이 비치는 창가의 삼색 고양이, 영화 같은 클로즈업\n"
            "(또는 영어로 직접: A calico cat by a sunset window, cinematic close-up)"
        )
        self.prompt_edit.setFixedHeight(80)
        self.prompt_edit.setStyleSheet(
            "QTextEdit {"
            " background-color: #252932;"
            " border: 1px solid #3F4554;"
            " border-radius: 4px;"
            " padding: 6px 8px;"
            " color: #E8EAED;"
            "}"
            "QTextEdit:focus { border: 1px solid #10B981; }"
        )
        outer.addWidget(self.prompt_edit)

        translate_row = QHBoxLayout()
        self.auto_translate_check = QCheckBox("한국어 → 영어 자동 번역 (Qwen3-VL 2B)")
        self.auto_translate_check.setChecked(True)
        self.auto_translate_check.setToolTip(
            "PixArt/SDXL/SD3 모두 영어 학습 99% — 한국어 직접 입력 시 결과가 부정확합니다. "
            "켜져 있으면 로컬 Qwen3-VL 2B (instruction-tuned) 로 자동 번역. "
            "첫 호출 5~15초, 이후 ~0.3초."
        )
        self.auto_translate_check.toggled.connect(self.auto_translate_toggled)
        translate_row.addWidget(self.auto_translate_check)
        translate_row.addStretch(1)
        outer.addLayout(translate_row)

        self.translated_label = QLabel("")
        self.translated_label.setWordWrap(True)
        self.translated_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.translated_label.setStyleSheet(
            "QLabel {"
            " color: #E8EAED; font-size: 12px; padding: 8px 10px;"
            " background: #1F2630; border: 1px solid #10B981;"
            " border-left: 3px solid #10B981; border-radius: 4px;"
            "}"
        )
        self.translated_label.setVisible(False)
        outer.addWidget(self.translated_label)

        # ---- 생성 옵션 (해상도/step/guidance/seed) ----
        opts = QVBoxLayout()
        opts.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("해상도:"))
        self.res_combo = QComboBox()
        # 라벨은 모델별 default_resolution 에 따라 _refresh_resolution_labels 가 갱신.
        for value in (1024, 768, 512):
            self.res_combo.addItem(f"{value}×{value}", value)
        self.res_combo.setCurrentIndex(0)
        row1.addWidget(self.res_combo, stretch=1)
        opts.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Step:"))
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(10, 50)
        self.steps_spin.setValue(30)
        row2.addWidget(self.steps_spin)
        row2.addWidget(QLabel("Guidance:"))
        self.guidance_spin = QSpinBox()
        self.guidance_spin.setRange(1, 10)
        self.guidance_spin.setValue(5)
        row2.addWidget(self.guidance_spin)
        row2.addStretch(1)
        opts.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Seed:"))
        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("비우면 랜덤")
        self.seed_edit.setFixedWidth(120)
        row3.addWidget(self.seed_edit)
        random_btn = QToolButton()
        random_btn.setText("🎲")
        random_btn.setToolTip("랜덤 seed 사용")
        random_btn.clicked.connect(lambda: self.seed_edit.clear())
        row3.addWidget(random_btn)
        row3.addStretch(1)
        opts.addLayout(row3)
        outer.addLayout(opts)

        # ---- 생성/취소 버튼 ----
        action_row = QHBoxLayout()
        self.generate_btn = QPushButton("생성하기")
        self.generate_btn.setStyleSheet(
            "QPushButton {"
            " background-color: #10B981; color: white; border: none;"
            " border-radius: 4px; padding: 8px 22px; font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #34D399; }"
            "QPushButton:pressed { background-color: #047857; }"
            "QPushButton:disabled { background-color: #2F343F; color: #6B7280; }"
        )
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        action_row.addWidget(self.generate_btn)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        action_row.addWidget(self.cancel_btn)
        action_row.addStretch(1)
        outer.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555; font-size: 11px;")
        outer.addWidget(self.status_label)

        # ---- 결과 미리보기 ----
        outer.addWidget(QLabel("결과:"))
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(280)
        self.preview_label.setStyleSheet(
            "border: 1px dashed #d1d5db; background: #f9fafb; color: #9ca3af;"
        )
        self.preview_label.setText("(생성된 이미지가 여기 표시됩니다)")
        outer.addWidget(self.preview_label, stretch=1)

        out_row = QHBoxLayout()
        self.editor_btn = QPushButton("편집기로 열기")
        self.editor_btn.setEnabled(False)
        self.editor_btn.clicked.connect(self._on_open_in_editor)
        out_row.addWidget(self.editor_btn)
        self.save_btn = QPushButton("저장…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        out_row.addWidget(self.save_btn)
        self.video_btn = QPushButton("영상에 추가")
        self.video_btn.setEnabled(False)
        self.video_btn.setToolTip("다음 업데이트 지원 예정")
        self.video_btn.clicked.connect(self._on_add_to_video)
        out_row.addWidget(self.video_btn)
        outer.addLayout(out_row)

        outer.addWidget(QLabel("최근 결과:"))
        self.recent_list = QListWidget()
        self.recent_list.setFlow(QListWidget.LeftToRight)
        self.recent_list.setIconSize(QSize(96, 96))
        self.recent_list.setFixedHeight(120)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.itemClicked.connect(self._on_recent_clicked)
        outer.addWidget(self.recent_list)

        # ---- 초기 모델 목록 populate (t2i 기본) ----
        self._populate_models("t2i")

    # ---- 모드 / 모델 picker 핸들러 ----

    def _on_mode_toggled(self, _checked: bool) -> None:
        new_mode = "t2i" if self.t2i_radio.isChecked() else "i2i"
        if new_mode == self._current_mode:
            return
        self._current_mode = new_mode
        self.i2i_group.setVisible(new_mode == "i2i")
        self._populate_models(new_mode)

    def _populate_models(self, mode: str) -> None:
        """카탈로그에서 모드별 모델 가져와 dropdown 채우기 — 품질순."""
        entries = t2i_models() if mode == "t2i" else i2i_models()
        # 사용자가 currentIndexChanged 콜백 폭주 안 하도록 일단 block.
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for e in entries:
            cached = _is_model_cached(e.repo_id, min_size_gb=e.estimated_size_gb * 0.5)
            cached_mark = "✓ " if cached else ""
            impl_mark = "" if e.is_implemented else " · 준비 중"
            label = f"{cached_mark}{e.display_name} ({e.estimated_size_gb:.1f}GB){impl_mark}"
            self.model_combo.addItem(label, e.id)
        # 기본 선택 우선순위:
        # 1) cached + is_implemented 인 첫 entry (즉시 generate 가능).
        # 2) is_implemented 만 (다운로드 후 generate 가능).
        # 3) 첫 entry (모두 미구현이라도 표시는 함).
        idx = 0
        chosen = False
        for i, e in enumerate(entries):
            if e.is_implemented and _is_model_cached(
                e.repo_id, min_size_gb=e.estimated_size_gb * 0.5
            ):
                idx = i
                chosen = True
                break
        if not chosen:
            for i, e in enumerate(entries):
                if e.is_implemented:
                    idx = i
                    break
        self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)
        self._refresh_model_info()
        # 모델 변경 알림 (initial populate 도 외부에 알려야 runtime 이 set_model 호출).
        cur_id = self.model_combo.currentData()
        if cur_id:
            self.model_changed.emit(cur_id)

    def _on_model_index_changed(self, _idx: int) -> None:
        model_id = self.model_combo.currentData()
        if not model_id:
            return
        self._refresh_model_info()
        self.model_changed.emit(model_id)

    def _refresh_model_info(self) -> None:
        """현재 선택 모델의 라이선스/속도/캐시 여부 + 생성/다운로드 버튼 상태."""
        model_id = self.model_combo.currentData()
        entry = by_id(model_id) if model_id else None
        if entry is None:
            self.model_info_label.setText("")
            self.generate_btn.setEnabled(False)
            self.download_btn.setVisible(False)
            return

        cached = _is_model_cached(entry.repo_id, min_size_gb=entry.estimated_size_gb * 0.5)
        info_parts = [
            entry.speed_label,
            f"라이선스: {entry.license_label}",
        ]
        if entry.license_note:
            info_parts.append(entry.license_note)
        self.model_info_label.setText(" · ".join(info_parts))

        if not entry.is_implemented:
            # 카탈로그엔 보이지만 백엔드 미구현 — 안내 + 생성 차단.
            self.generate_btn.setEnabled(False)
            self.download_btn.setVisible(False)
            self.status_label.setText(f"⏳ {entry.display_name} 는 다음 업데이트 지원 예정")
            return

        if cached:
            self.generate_btn.setEnabled(True)
            self.download_btn.setVisible(False)
            self.status_label.setText("")
        else:
            # 미설치 — 다운로드 버튼 표시 + 생성 차단.
            self.generate_btn.setEnabled(False)
            self.download_btn.setText(f"다운로드 ({entry.estimated_size_gb:.1f}GB)")
            self.download_btn.setVisible(True)
            self.status_label.setText(
                f"⬇ {entry.display_name} 미설치 — 다운로드 후 생성 가능"
            )

        # 모델별 추천 해상도를 dropdown 라벨에 (추천) 으로 표시.
        self._refresh_resolution_labels(entry)

    def _refresh_resolution_labels(self, entry: ImageGenModelEntry) -> None:
        """현재 선택 모델의 default_resolution 항목에 '(추천)' 라벨 표시.

        SDXL/SD3/PixArt 모두 1024 학습 기본이지만 향후 모델별로 다를 수 있어 동적 처리.
        """
        default_res = entry.default_resolution
        self.res_combo.blockSignals(True)
        for i in range(self.res_combo.count()):
            value = self.res_combo.itemData(i)
            base = f"{value}×{value}"
            self.res_combo.setItemText(i, f"{base} (추천)" if value == default_res else base)
        # 현재 선택값이 추천 해상도와 다른 default 일 경우 자동으로 (추천) 으로 이동.
        # 단 사용자가 명시적으로 다른 해상도를 골랐을 수 있어 — populate 직후 한 번만.
        self.res_combo.blockSignals(False)

    def refresh_after_download(self) -> None:
        """다운로드 완료 후 호출 — 캐시 상태 다시 검사하고 UI 갱신."""
        self._refresh_model_info()
        # ✓ 마크 갱신을 위해 dropdown 라벨도 다시 그림.
        cur_id = self.model_combo.currentData()
        self._populate_models(self._current_mode)
        if cur_id:
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == cur_id:
                    self.model_combo.blockSignals(True)
                    self.model_combo.setCurrentIndex(i)
                    self.model_combo.blockSignals(False)
                    break
        self._refresh_model_info()

    def _on_download_clicked(self) -> None:
        model_id = self.model_combo.currentData()
        if model_id:
            self.download_requested.emit(model_id)

    # ---- i2i reference 핸들러 ----

    def _on_browse_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "원본 이미지 선택",
            "",
            "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.webp);;모든 파일 (*)",
        )
        if not path:
            return
        self._set_reference_from_path(Path(path), label=Path(path).name)

    def _set_reference_from_path(
        self, path: Path, *, label: Optional[str] = None,
        switch_to_i2i: bool = False,
    ) -> None:
        """파일 path 로 원본 세팅 — file picker / clipboard 의 url 분기에서 호출."""
        self._reference_path = path
        self.ref_path_label.setText(label or path.name)
        pix = QPixmap(str(path))
        if not pix.isNull():
            scaled = pix.scaled(
                self.ref_preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.ref_preview.setPixmap(scaled)
        if switch_to_i2i and not self.i2i_radio.isChecked():
            self.i2i_radio.setChecked(True)

    def paste_reference_from_clipboard(self) -> bool:
        """클립보드의 이미지를 i2i 원본으로 세팅 + i2i 모드 자동 전환.

        우선순위: QImage (스크린샷/이미지 앱 copy) → file URL (탐색기에서 이미지 파일 copy).
        성공 시 True. 클립보드에 이미지 없으면 False (호출자가 텍스트 paste 등 fallback).
        """
        from PySide6.QtGui import QGuiApplication, QImage
        clipboard = QGuiApplication.clipboard()

        # 1) raw 이미지 (스크린샷 / 이미지 앱 copy) — 가장 흔한 케이스.
        img = clipboard.image()
        if not img.isNull():
            return self._set_reference_from_qimage(img, label="(클립보드 이미지)")

        # 2) 파일 URL — 탐색기에서 이미지 파일 copy 한 경우.
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                if not url.isLocalFile():
                    continue
                file_path = url.toLocalFile()
                file_img = QImage(file_path)
                if not file_img.isNull():
                    self._set_reference_from_path(
                        Path(file_path),
                        label=Path(file_path).name,
                        switch_to_i2i=True,
                    )
                    self.status_label.setText(
                        f"📋 클립보드: {Path(file_path).name} 을 원본으로 사용"
                    )
                    return True
        return False

    def _set_reference_from_qimage(self, q_image, *, label: str) -> bool:
        """QImage → 임시 PNG 로 저장 후 _reference_path 세팅 + i2i 모드 전환."""
        import tempfile
        import os
        fd, tmp = tempfile.mkstemp(prefix="kstudio_clip_", suffix=".png")
        os.close(fd)
        if not q_image.save(tmp, "PNG"):
            return False
        self._reference_path = Path(tmp)
        self.ref_path_label.setText(label)
        pix = QPixmap.fromImage(q_image).scaled(
            self.ref_preview.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.ref_preview.setPixmap(pix)
        # 클립보드 paste 는 명백한 i2i 의도 → 모드 자동 전환.
        if not self.i2i_radio.isChecked():
            self.i2i_radio.setChecked(True)
        self.status_label.setText("📋 클립보드 이미지를 원본으로 사용 — i2i 모드로 전환")
        return True

    def _on_strength_changed(self, value: int) -> None:
        self.strength_label.setText(f"{value / 100:.2f}")

    # ---- 생성 핸들러 ----

    def _on_generate_clicked(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "이미지 생성", "프롬프트를 입력해주세요.")
            return
        if self._current_mode == "i2i" and self._reference_path is None:
            QMessageBox.warning(
                self, "이미지 생성",
                "Image-to-Image 모드에서는 원본 이미지를 선택해주세요.",
            )
            return
        res = int(self.res_combo.currentData())
        seed_text = self.seed_edit.text().strip()
        try:
            seed = int(seed_text) if seed_text else None
        except ValueError:
            seed = None
        params = dict(
            width=res, height=res,
            num_inference_steps=int(self.steps_spin.value()),
            guidance_scale=float(self.guidance_spin.value()),
            seed=seed,
        )
        if self._current_mode == "i2i" and self._reference_path is not None:
            params["reference_image"] = self._reference_path
            params["strength"] = self.strength_slider.value() / 100.0
        self.generate_requested.emit(prompt, params)

    # ---- 결과 버튼 핸들러 ----

    def _on_open_in_editor(self) -> None:
        if self._current_image_path:
            self.open_in_editor_requested.emit(self._current_image_path)

    def _on_save(self) -> None:
        if self._current_image_path:
            self.save_as_requested.emit(self._current_image_path)

    def _on_add_to_video(self) -> None:
        if self._current_image_path:
            self.add_to_video_requested.emit(self._current_image_path)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.show_result(path)

    # ---- runtime 시그널 핸들러 ----

    def set_generating(self, busy: bool) -> None:
        self.generate_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText("준비 중…")
            self.translated_label.setVisible(False)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            # busy 끝났을 때 다시 모델 상태 확인 (모델 변경 후 generate 한 경우 등).
            self._refresh_model_info()

    def set_load_state(self, loading: bool) -> None:
        if loading:
            self.status_label.setText("모델 메모리에 올리는 중… 처음엔 10~60초 걸릴 수 있어요")
            self.generate_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)

    def set_step(self, current: int, total: int) -> None:
        if total <= 0:
            return
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        pct = int(current / total * 100)
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Step {current}/{total}")

    def show_result(self, path: str) -> None:
        self._current_image_path = path
        pix = QPixmap(path)
        if pix.isNull():
            self.preview_label.setText(f"(이미지 로드 실패: {path})")
            return
        scaled = pix.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.editor_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.status_label.setText("완료")
        self._push_recent(path)

    def show_error(self, message: str) -> None:
        self.status_label.setText(f"오류: {message}")
        self.progress_bar.setVisible(False)

    def show_cancelled(self) -> None:
        self.status_label.setText("취소됨")
        self.progress_bar.setVisible(False)

    def show_translation_started(self) -> None:
        self.status_label.setText("한국어 → 영어 번역 중… (첫 호출 5~15초, 이후 즉시)")
        self.translated_label.setVisible(False)

    def show_translation(self, source_ko: str, translated_en: str) -> None:
        ko_short = source_ko if len(source_ko) <= 200 else source_ko[:200] + "…"
        en_short = translated_en if len(translated_en) <= 200 else translated_en[:200] + "…"
        self.translated_label.setText(
            f"<b style='color:#10B981;'>📝 한 → 영 번역됨</b><br>"
            f"<span style='color:#9CA3AF;'>원문:</span> {ko_short}<br>"
            f"<span style='color:#9CA3AF;'>영어:</span> <b>{en_short}</b>"
        )
        self.translated_label.setVisible(True)

    def _push_recent(self, path: str, max_keep: int = 8) -> None:
        if path in self._recent_paths:
            return
        self._recent_paths.append(path)
        pix = QPixmap(path)
        if pix.isNull():
            return
        thumb = pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        item = QListWidgetItem()
        from PySide6.QtGui import QIcon
        item.setIcon(QIcon(thumb))
        item.setData(Qt.UserRole, path)
        item.setSizeHint(QSize(110, 110))
        self.recent_list.addItem(item)
        while self.recent_list.count() > max_keep:
            removed = self.recent_list.takeItem(0)
            removed_path = removed.data(Qt.UserRole)
            if removed_path in self._recent_paths:
                self._recent_paths.remove(removed_path)


class ImageGenDialog(QDialog):
    """비모달 별창 형태 이미지 생성 패널 — 모델 카탈로그 + t2i/i2i 모드 지원."""

    image_for_editor = Signal(str)
    image_for_video = Signal(str)
    closed = Signal()

    def __init__(
        self,
        runtime: Optional[ImageGenRuntime] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ImageGenDialog")
        self.setWindowTitle("이미지 생성")
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.resize(480, 820)

        self._runtime: Optional[ImageGenRuntime] = runtime
        self._download_window: Optional[ModelDownloadWindow] = None
        self._download_job = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._panel = _ReadyPanel()
        self._panel.generate_requested.connect(self._on_generate_requested)
        self._panel.cancel_requested.connect(self._on_cancel)
        self._panel.open_in_editor_requested.connect(self.image_for_editor)
        self._panel.save_as_requested.connect(self._save_as)
        self._panel.add_to_video_requested.connect(self.image_for_video)
        self._panel.auto_translate_toggled.connect(self._on_auto_translate_toggled)
        self._panel.model_changed.connect(self._on_model_changed)
        self._panel.download_requested.connect(self._on_download_requested)
        outer.addWidget(self._panel)

        # Ctrl+V — 다이얼로그가 활성화된 상태에서 클립보드 이미지 → i2i 원본 자동 세팅.
        # 사용자 결정 2026-05-27: prompt 칸에 focus 있을 땐 텍스트 paste 가 우선 (충돌 회피).
        self._paste_shortcut = QShortcut(QKeySequence.Paste, self)
        self._paste_shortcut.setContext(Qt.WindowShortcut)
        self._paste_shortcut.activated.connect(self._handle_paste_shortcut)

    def _ensure_runtime(self) -> ImageGenRuntime:
        if self._runtime is None:
            self._runtime = ImageGenRuntime()
        if getattr(self._runtime, "_dialog_wired", False) is False:
            self._runtime.load_started.connect(
                lambda: self._panel.set_load_state(True)
            )
            self._runtime.load_finished.connect(
                lambda: self._panel.set_load_state(False)
            )
            self._runtime.generation_started.connect(
                lambda: self._panel.set_generating(True)
            )
            self._runtime.step_progress.connect(self._panel.set_step)
            self._runtime.image_ready.connect(self._on_image_ready)
            self._runtime.generation_failed.connect(self._on_failed)
            self._runtime.generation_cancelled.connect(self._on_cancelled)
            self._runtime.translate_started.connect(
                self._panel.show_translation_started
            )
            self._runtime.translated.connect(self._panel.show_translation)
            self._runtime._dialog_wired = True   # type: ignore[attr-defined]
        return self._runtime

    def _on_auto_translate_toggled(self, on: bool) -> None:
        rt = self._ensure_runtime()
        if hasattr(rt, "set_auto_translate"):
            rt.set_auto_translate(on)

    def _handle_paste_shortcut(self) -> None:
        """Ctrl+V — focus 위치 보고 텍스트 paste vs 이미지 paste 분기.

        - prompt_edit / seed_edit 에 focus → 기본 텍스트 paste 동작 유지 (사용자가 텍스트 입력 중).
        - 그 외 (다이얼로그 빈 영역, dropdown 등) → 클립보드 이미지를 i2i 원본으로 세팅.
        """
        focus_w = self.focusWidget()
        if focus_w is self._panel.prompt_edit:
            self._panel.prompt_edit.paste()
            return
        if focus_w is self._panel.seed_edit:
            self._panel.seed_edit.paste()
            return
        # 그 외 → 이미지 paste 시도.
        if not self._panel.paste_reference_from_clipboard():
            # 클립보드에 이미지 없으면 — 빈 영역에선 그냥 무시.
            self._panel.status_label.setText(
                "클립보드에 이미지가 없습니다. 스크린샷 또는 이미지 복사 후 다시 시도."
            )

    def _on_model_changed(self, model_id: str) -> None:
        """사용자가 dropdown 에서 다른 모델 선택 — runtime 의 backend 교체."""
        rt = self._ensure_runtime()
        try:
            rt.set_model(model_id)
        except Exception as exc:
            _log.exception("set_model failed")
            QMessageBox.warning(self, "모델 변경 실패", str(exc))

    def _on_download_requested(self, model_id: str) -> None:
        """모델 다운로드 시작 — ModelDownloadWindow 띄움."""
        entry = by_id(model_id)
        if entry is None:
            return
        if self._download_window is not None and self._download_job is not None:
            self._download_window.show()
            self._download_window.raise_()
            return

        from ...agent.models.downloader import ModelDownloadJob

        win = ModelDownloadWindow(
            repo_id=entry.repo_id,
            display_name=entry.display_name,
            estimated_size_gb=entry.estimated_size_gb,
            parent=self,
        )
        win.set_phase("downloading")
        win.show()

        job = ModelDownloadJob(
            repo_id=entry.repo_id,
            estimated_size_bytes=estimated_size_bytes(entry),
        )
        job.download_progress.connect(win.update_progress)
        job.finished.connect(lambda _rid: self._on_download_finished(win))
        job.error.connect(lambda msg: self._on_download_error(win, msg))
        self._download_window = win
        self._download_job = job
        job.start()

    def _on_download_finished(self, win: ModelDownloadWindow) -> None:
        win.set_phase("done")
        win.append_log("✓ 다운로드 완료. 이제 프롬프트를 입력해 생성할 수 있습니다.")
        self._download_window = None
        self._download_job = None
        self._panel.refresh_after_download()

    def _on_download_error(self, win: ModelDownloadWindow, msg: str) -> None:
        win.set_phase("error")
        win.append_log(f"오류: {msg}")
        self._download_window = None
        self._download_job = None

    def _on_generate_requested(self, prompt: str, params: dict) -> None:
        rt = self._ensure_runtime()
        self._panel.set_generating(True)
        rt.generate(prompt, **params)

    def _on_cancel(self) -> None:
        if self._runtime is not None:
            self._runtime.cancel()

    def _on_image_ready(self, path: str) -> None:
        self._panel.set_generating(False)
        self._panel.show_result(path)

    def _on_failed(self, msg: str) -> None:
        self._panel.set_generating(False)
        self._panel.show_error(msg)

    def _on_cancelled(self) -> None:
        self._panel.set_generating(False)
        self._panel.show_cancelled()

    def _save_as(self, src_path: str) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "이미지 저장",
            "",
            "PNG 이미지 (*.png);;모든 파일 (*)",
        )
        if not target:
            return
        try:
            import shutil
            shutil.copyfile(src_path, target)
        except Exception as exc:
            QMessageBox.warning(self, "저장 실패", f"저장 중 오류: {exc}")

    def shutdown(self) -> None:
        if self._runtime is not None:
            try:
                self._runtime.close()
            except Exception:
                _log.exception("ImageGenDialog.shutdown: runtime.close 오류 무시")

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)
