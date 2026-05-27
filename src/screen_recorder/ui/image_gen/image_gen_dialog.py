"""ImageGenDialog — 비모달 별창 형태 이미지 생성 패널.

상태:
- **uninstalled**: 모델 미다운로드. 다운로드 안내 + 버튼.
- **downloading**: ModelDownloadWindow 별창이 떠 있음. 패널은 "다운로드 진행 중" 표시.
- **ready**: 프롬프트 입력 + 생성/취소 + 미리보기 + 액션 버튼 + 최근 결과 스트립.

설계 변경 (2026-05-27 사용자 요청):
- 기존: QDockWidget — 메인 윈도우에 도킹
- 변경: QDialog 비모달 별창 — `Qt.Window` 플래그로 main 과 독립. 떠있어도 메인의
  도구 자유롭게 쓸 수 있고 (modal=False), 위치 자유 이동.

진입점:
- 도구 팔레트 "이미지 생성" 액션 (자동 누끼 아래)
- 창 메뉴 "이미지 생성" (Ctrl+Shift+G)

다운로드 / 모델 로드 / 생성 흐름:
- 다운로드: `agent/models/downloader.ModelDownloadJob` 재사용.
- 모델 로드: `ImageGenRuntime` 의 첫 generate() 시점에 자동 (load_started/load_finished 시그널).
- 생성: prompt + 옵션 → runtime.generate() → step_progress 시그널 → image_ready.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...image_gen import ImageGenRuntime
from ...image_gen.model_meta import MODEL_META, estimated_size_bytes
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


class _UninstalledPanel(QWidget):
    """미설치 상태 — 다운로드 안내 + 버튼."""

    download_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("이미지 생성 — PixArt-Sigma")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        info = QLabel(
            f"첫 사용 시 모델을 다운로드합니다.\n"
            f"• 크기: 약 {MODEL_META.estimated_size_gb:.1f} GB\n"
            f"• GPU 메모리: 약 {MODEL_META.estimated_vram_gb:.1f} GB (CPU offload 모드)\n"
            f"• 생성 속도: 1024×1024 약 20초/장 (RTX 5060 Ti 기준)\n"
            f"• HuggingFace 계정 / 로그인 불필요 (ungated)\n\n"
            f"한 번 다운로드하면 이후엔 즉시 사용 가능합니다."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #444;")
        layout.addWidget(info)

        layout.addSpacing(8)
        btn = QPushButton(f"모델 다운로드 (~{MODEL_META.estimated_size_gb:.1f} GB)")
        btn.setStyleSheet("padding: 8px 16px; font-size: 13px;")
        btn.clicked.connect(self.download_clicked)
        layout.addWidget(btn)

        layout.addStretch(1)


class _ReadyPanel(QWidget):
    """준비완료 상태 — 프롬프트 + 옵션 + 미리보기 + 액션 + 최근 결과."""

    generate_requested = Signal(str, dict)
    cancel_requested = Signal()
    open_in_editor_requested = Signal(str)
    save_as_requested = Signal(str)
    add_to_video_requested = Signal(str)
    auto_translate_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_image_path: Optional[str] = None
        self._recent_paths: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addWidget(QLabel("프롬프트 (한국어 OK — 자동으로 영어로 번역):"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "예: 노을이 비치는 창가의 삼색 고양이, 영화 같은 클로즈업\n"
            "(또는 영어로 직접: A calico cat by a sunset window, cinematic close-up)"
        )
        self.prompt_edit.setFixedHeight(80)
        # 메인 배경과 동화돼 입력 영역인지 안 보이는 회귀 fix (사용자 보고 2026-05-27).
        # 한 단계 밝은 surface + border + focus 시 emerald 강조.
        self.prompt_edit.setStyleSheet(
            "QTextEdit {"
            " background-color: #252932;"
            " border: 1px solid #3F4554;"
            " border-radius: 4px;"
            " padding: 6px 8px;"
            " color: #E8EAED;"
            "}"
            "QTextEdit:focus {"
            " border: 1px solid #10B981;"
            "}"
        )
        outer.addWidget(self.prompt_edit)

        translate_row = QHBoxLayout()
        self.auto_translate_check = QCheckBox("한국어 → 영어 자동 번역 (Claude)")
        self.auto_translate_check.setChecked(True)
        self.auto_translate_check.setToolTip(
            "PixArt 는 영어 학습이 99% 라 한국어 직접 입력 시 결과가 부정확합니다. "
            "켜져 있으면 KStudio 의 Claude 정액제로 자동 번역 (Haiku, 1~2초 추가)."
        )
        self.auto_translate_check.toggled.connect(self.auto_translate_toggled)
        translate_row.addWidget(self.auto_translate_check)
        translate_row.addStretch(1)
        outer.addLayout(translate_row)

        self.translated_label = QLabel("")
        self.translated_label.setWordWrap(True)
        self.translated_label.setStyleSheet(
            "color: #6b7280; font-size: 11px; font-style: italic; "
            "padding: 4px 6px; background: #f3f4f6; border-radius: 3px;"
        )
        self.translated_label.setVisible(False)
        outer.addWidget(self.translated_label)

        opts = QVBoxLayout()
        opts.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("해상도:"))
        self.res_combo = QComboBox()
        for label, value in [("1024×1024", 1024), ("768×768", 768), ("512×512", 512)]:
            self.res_combo.addItem(label, value)
        self.res_combo.setCurrentIndex(0)
        row1.addWidget(self.res_combo, stretch=1)
        opts.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Step:"))
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(10, 40)
        self.steps_spin.setValue(MODEL_META.default_steps)
        row2.addWidget(self.steps_spin)
        row2.addWidget(QLabel("Guidance:"))
        self.guidance_spin = QSpinBox()
        self.guidance_spin.setRange(1, 10)
        self.guidance_spin.setValue(int(MODEL_META.default_guidance))
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

        action_row = QHBoxLayout()
        self.generate_btn = QPushButton("생성하기")
        # 주요 액션 강조 — 다크 배경과 명확히 구분 (사용자 보고 2026-05-27 "어딜 눌러야할지를 모르겠네").
        # image 팔레트의 primary (#10B981 emerald) — 모드 무관 박아넣음.
        self.generate_btn.setStyleSheet(
            "QPushButton {"
            " background-color: #10B981;"
            " color: white;"
            " border: none;"
            " border-radius: 4px;"
            " padding: 8px 22px;"
            " font-weight: bold;"
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

        outer.addWidget(QLabel("결과:"))
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(300)
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
        self.video_btn.setToolTip("다음 업데이트 지원 예정 — 현재는 [편집기로 열기] / [저장] 사용")
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

    def _on_generate_clicked(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "이미지 생성", "프롬프트를 입력해주세요.")
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
        self.generate_requested.emit(prompt, params)

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

    def set_load_state(self, loading: bool) -> None:
        if loading:
            self.status_label.setText(
                "모델 메모리에 올리는 중… 처음엔 10~60초 걸릴 수 있어요"
            )
            self.generate_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
        else:
            pass

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
        self.status_label.setText("한국어 → 영어 번역 중…")
        self.translated_label.setVisible(False)

    def show_translation(self, source_ko: str, translated_en: str) -> None:
        en_short = translated_en if len(translated_en) <= 200 else translated_en[:200] + "…"
        self.translated_label.setText(f"번역됨 → {en_short}")
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
        item.setIcon(__import__("PySide6.QtGui", fromlist=["QIcon"]).QIcon(thumb))
        item.setData(Qt.UserRole, path)
        item.setSizeHint(QSize(110, 110))
        self.recent_list.addItem(item)
        while self.recent_list.count() > max_keep:
            removed = self.recent_list.takeItem(0)
            removed_path = removed.data(Qt.UserRole)
            if removed_path in self._recent_paths:
                self._recent_paths.remove(removed_path)


class ImageGenDialog(QDialog):
    """비모달 별창 형태 이미지 생성 패널.

    `Qt.Window` 플래그로 main window 와 독립된 별창. 비모달이라 떠있는 동안에도
    메인의 도구는 자유롭게 사용. 닫기 (X) 는 hide() 와 같아 다음 토글로 재표시 가능
    (ModelDownloadWindow 와 같은 패턴).
    """

    # MainWindow 가 받는 시그널.
    image_for_editor = Signal(str)
    image_for_video = Signal(str)
    closed = Signal()                  # X 닫기 — main_window 가 메뉴 체크 해제 용

    def __init__(
        self,
        runtime: Optional[ImageGenRuntime] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ImageGenDialog")
        self.setWindowTitle("이미지 생성")
        # 비모달 + 별창 — main 도구 사용 자유.
        self.setModal(False)
        self.setWindowFlag(Qt.Window, True)
        self.resize(460, 720)

        # runtime 은 lazy — 미설치 상태에선 backend 까지 만들 필요 없음.
        self._runtime: Optional[ImageGenRuntime] = runtime
        self._download_window: Optional[ModelDownloadWindow] = None
        self._download_job = None

        # QDialog 안에 stack — setWidget 이 아니라 layout 으로.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._uninstalled_panel = _UninstalledPanel()
        self._uninstalled_panel.download_clicked.connect(self._start_download)
        self._stack.addWidget(self._uninstalled_panel)

        self._ready_panel = _ReadyPanel()
        self._ready_panel.generate_requested.connect(self._on_generate_requested)
        self._ready_panel.cancel_requested.connect(self._on_cancel)
        self._ready_panel.open_in_editor_requested.connect(self.image_for_editor)
        self._ready_panel.save_as_requested.connect(self._save_as)
        self._ready_panel.add_to_video_requested.connect(self.image_for_video)
        self._ready_panel.auto_translate_toggled.connect(self._on_auto_translate_toggled)
        self._stack.addWidget(self._ready_panel)

        if _is_model_cached(MODEL_META.repo_id):
            self._show_ready()
        else:
            self._stack.setCurrentWidget(self._uninstalled_panel)

    def _ensure_runtime(self) -> ImageGenRuntime:
        if self._runtime is None:
            self._runtime = ImageGenRuntime()
        if getattr(self._runtime, "_dialog_wired", False) is False:
            self._runtime.load_started.connect(
                lambda: self._ready_panel.set_load_state(True)
            )
            self._runtime.load_finished.connect(
                lambda: self._ready_panel.set_load_state(False)
            )
            self._runtime.generation_started.connect(
                lambda: self._ready_panel.set_generating(True)
            )
            self._runtime.step_progress.connect(self._ready_panel.set_step)
            self._runtime.image_ready.connect(self._on_image_ready)
            self._runtime.generation_failed.connect(self._on_failed)
            self._runtime.generation_cancelled.connect(self._on_cancelled)
            self._runtime.translate_started.connect(
                self._ready_panel.show_translation_started
            )
            self._runtime.translated.connect(self._ready_panel.show_translation)
            self._runtime._dialog_wired = True   # type: ignore[attr-defined]
        return self._runtime

    def _on_auto_translate_toggled(self, on: bool) -> None:
        rt = self._ensure_runtime()
        if hasattr(rt, "set_auto_translate"):
            rt.set_auto_translate(on)

    def _start_download(self) -> None:
        if self._download_window is not None and self._download_job is not None:
            self._download_window.show()
            self._download_window.raise_()
            return

        from ...agent.models.downloader import ModelDownloadJob

        win = ModelDownloadWindow(
            repo_id=MODEL_META.repo_id,
            display_name=MODEL_META.display_name,
            estimated_size_gb=MODEL_META.estimated_size_gb,
            parent=self,
        )
        win.set_phase("downloading")
        win.show()

        job = ModelDownloadJob(
            repo_id=MODEL_META.repo_id,
            estimated_size_bytes=estimated_size_bytes(),
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
        self._show_ready()

    def _on_download_error(self, win: ModelDownloadWindow, msg: str) -> None:
        win.set_phase("error")
        win.append_log(f"오류: {msg}")
        self._download_window = None
        self._download_job = None

    def _show_ready(self) -> None:
        self._stack.setCurrentWidget(self._ready_panel)

    def _on_generate_requested(self, prompt: str, params: dict) -> None:
        rt = self._ensure_runtime()
        self._ready_panel.set_generating(True)
        rt.generate(prompt, **params)

    def _on_cancel(self) -> None:
        if self._runtime is not None:
            self._runtime.cancel()

    def _on_image_ready(self, path: str) -> None:
        self._ready_panel.set_generating(False)
        self._ready_panel.show_result(path)

    def _on_failed(self, msg: str) -> None:
        self._ready_panel.set_generating(False)
        self._ready_panel.show_error(msg)

    def _on_cancelled(self) -> None:
        self._ready_panel.set_generating(False)
        self._ready_panel.show_cancelled()

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

    # ---- 비모달 close 패턴 — ModelDownloadWindow 와 같이 hide 처리 ----
    def closeEvent(self, event):  # noqa: N802 (Qt 시그니처)
        # closed 시그널 → main_window 가 메뉴 체크 + settings 영속.
        self.closed.emit()
        super().closeEvent(event)
