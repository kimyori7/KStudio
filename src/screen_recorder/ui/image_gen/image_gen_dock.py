"""ImageGenDock — KStudio 우측 사이드 패널로 도킹되는 이미지 생성 위젯.

상태:
- **uninstalled**: 모델 미다운로드. 다운로드 안내 + 버튼.
- **downloading**: ModelDownloadWindow 별창이 떠 있음. 패널은 "다운로드 진행 중" 표시.
- **ready**: 프롬프트 입력 + 생성/취소 + 미리보기 + 액션 버튼 + 최근 결과 스트립.

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
    QComboBox,
    QDockWidget,
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
        # snapshots/<sha>/<file> 들 안에서 큰 safetensors 가 있으면 캐시 완료로 봄.
        # 다운로드 중에는 .incomplete 또는 partial 파일이 있어서 size 합으로 판정.
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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_image_path: Optional[str] = None
        self._recent_paths: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ---- 프롬프트 ----
        outer.addWidget(QLabel("프롬프트 (한국어/영어):"))
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "예: 노을이 비치는 창가의 삼색 고양이, 영화 같은 클로즈업"
        )
        self.prompt_edit.setFixedHeight(80)
        outer.addWidget(self.prompt_edit)

        # ---- 옵션 (해상도 / step / guidance / seed) ----
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

        # ---- 액션 (생성 / 취소) ----
        action_row = QHBoxLayout()
        self.generate_btn = QPushButton("생성하기")
        self.generate_btn.setStyleSheet("padding: 6px 14px; font-weight: bold;")
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        action_row.addWidget(self.generate_btn)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        action_row.addWidget(self.cancel_btn)
        action_row.addStretch(1)
        outer.addLayout(action_row)

        # ---- 진행률 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555; font-size: 11px;")
        outer.addWidget(self.status_label)

        # ---- 미리보기 ----
        outer.addWidget(QLabel("결과:"))
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(280)
        self.preview_label.setStyleSheet(
            "border: 1px dashed #d1d5db; background: #f9fafb; color: #9ca3af;"
        )
        self.preview_label.setText("(생성된 이미지가 여기 표시됩니다)")
        outer.addWidget(self.preview_label, stretch=1)

        # ---- 결과 액션 ----
        out_row = QHBoxLayout()
        self.editor_btn = QPushButton("편집기로 열기")
        self.editor_btn.setEnabled(False)
        self.editor_btn.clicked.connect(self._on_open_in_editor)
        out_row.addWidget(self.editor_btn)
        self.save_btn = QPushButton("저장…")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        out_row.addWidget(self.save_btn)
        # "영상에 추가" 는 Phase 6 이후 — 정지 이미지를 영상 타임라인 클립으로 변환하는
        # VideoTab.add_static_image_clip 구현이 선행 필요. 첫 출시에선 placeholder.
        self.video_btn = QPushButton("영상에 추가")
        self.video_btn.setEnabled(False)
        self.video_btn.setToolTip("다음 업데이트 지원 예정 — 현재는 [편집기로 열기] / [저장] 사용")
        self.video_btn.clicked.connect(self._on_add_to_video)
        out_row.addWidget(self.video_btn)
        outer.addLayout(out_row)

        # ---- 최근 결과 스트립 ----
        outer.addWidget(QLabel("최근 결과:"))
        self.recent_list = QListWidget()
        self.recent_list.setFlow(QListWidget.LeftToRight)
        self.recent_list.setIconSize(QSize(96, 96))
        self.recent_list.setFixedHeight(120)
        self.recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.recent_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent_list.itemClicked.connect(self._on_recent_clicked)
        outer.addWidget(self.recent_list)

    # ---- 내부 액션 ----
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

    # ---- 외부에서 호출되는 상태 갱신 ----
    def set_generating(self, busy: bool) -> None:
        self.generate_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.progress_bar.setVisible(busy)
        if not busy:
            self.progress_bar.setValue(0)

    def set_load_state(self, loading: bool) -> None:
        """모델 콜드 로드 표시 (generate 첫 호출 시점에 5~15초)."""
        if loading:
            self.status_label.setText("모델 로딩 중… (첫 생성은 추가 5~15초)")
        else:
            self.status_label.setText("")

    def set_step(self, current: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(current / total * 100)
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Step {current}/{total}")

    def show_result(self, path: str) -> None:
        self._current_image_path = path
        pix = QPixmap(path)
        if pix.isNull():
            self.preview_label.setText(f"(이미지 로드 실패: {path})")
            return
        # 미리보기 영역에 fit — 너무 큰 이미지는 축소.
        scaled = pix.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.editor_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        # video_btn 은 Phase 6+ 까지 비활성 유지.
        self.status_label.setText("완료")
        self._push_recent(path)

    def show_error(self, message: str) -> None:
        self.status_label.setText(f"오류: {message}")
        self.progress_bar.setVisible(False)

    def show_cancelled(self) -> None:
        self.status_label.setText("취소됨")
        self.progress_bar.setVisible(False)

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
        # max_keep 넘어가면 앞에서 제거.
        while self.recent_list.count() > max_keep:
            removed = self.recent_list.takeItem(0)
            removed_path = removed.data(Qt.UserRole)
            if removed_path in self._recent_paths:
                self._recent_paths.remove(removed_path)


class ImageGenDock(QDockWidget):
    """KStudio 우측 사이드 패널 — 이미지 생성 모듈 통합 진입점.

    Phase 3 (다운로드 가드) + Phase 4 (UI) + Phase 5 (편집기/타임라인 통합) 를 통합한 셸.
    `MainWindow` 가 이 dock 을 만들고 `image_for_editor` / `image_for_video` 시그널을
    각각 적절한 슬롯에 연결.
    """

    # MainWindow 가 받는 시그널.
    image_for_editor = Signal(str)        # 결과 png 경로 → EditTab 으로 열기
    image_for_video = Signal(str)         # 결과 png 경로 → 활성 VideoTab 타임라인 추가

    def __init__(
        self,
        runtime: Optional[ImageGenRuntime] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("이미지 생성", parent)
        self.setObjectName("ImageGenDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # runtime 은 lazy — 미설치 상태에선 backend 까지 만들 필요 없음.
        self._runtime: Optional[ImageGenRuntime] = runtime
        self._download_window: Optional[ModelDownloadWindow] = None
        self._download_job = None

        self._stack = QStackedWidget()
        self.setWidget(self._stack)

        self._uninstalled_panel = _UninstalledPanel()
        self._uninstalled_panel.download_clicked.connect(self._start_download)
        self._stack.addWidget(self._uninstalled_panel)

        self._ready_panel = _ReadyPanel()
        self._ready_panel.generate_requested.connect(self._on_generate_requested)
        self._ready_panel.cancel_requested.connect(self._on_cancel)
        self._ready_panel.open_in_editor_requested.connect(self.image_for_editor)
        self._ready_panel.save_as_requested.connect(self._save_as)
        self._ready_panel.add_to_video_requested.connect(self.image_for_video)
        self._stack.addWidget(self._ready_panel)

        # 초기 상태 결정.
        if _is_model_cached(MODEL_META.repo_id):
            self._show_ready()
        else:
            self._stack.setCurrentWidget(self._uninstalled_panel)

    # ---- runtime 진입 ----
    def _ensure_runtime(self) -> ImageGenRuntime:
        if self._runtime is None:
            self._runtime = ImageGenRuntime()
        # 시그널 와이어링 — runtime 이 바뀌어도 안전하게 한 번만.
        if getattr(self._runtime, "_dock_wired", False) is False:
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
            self._runtime._dock_wired = True   # type: ignore[attr-defined]
        return self._runtime

    # ---- 다운로드 ----
    def _start_download(self) -> None:
        # 이미 진행 중이면 창만 다시 띄움.
        if self._download_window is not None and self._download_job is not None:
            self._download_window.show()
            self._download_window.raise_()
            return

        # Lazy import — 에이전트 모델 다운로더 재사용.
        from ...agent.models.downloader import ModelDownloadJob

        win = ModelDownloadWindow(
            repo_id=MODEL_META.repo_id,
            display_name=MODEL_META.display_name,
            estimated_size_gb=MODEL_META.estimated_size_gb,
            parent=self.window(),
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

    # ---- 생성 흐름 ----
    def _on_generate_requested(self, prompt: str, params: dict) -> None:
        rt = self._ensure_runtime()
        ok = rt.generate(prompt, **params)
        if not ok:
            # 이미 진행 중이거나 prompt 빈 경우 — runtime 이 알아서 generation_failed emit.
            return

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

    # ---- 저장 ----
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

    # ---- 수명 ----
    def shutdown(self) -> None:
        """MainWindow 종료 hook — runtime 정리."""
        if self._runtime is not None:
            try:
                self._runtime.close()
            except Exception:
                _log.exception("ImageGenDock.shutdown: runtime.close 오류 무시")
        if self._download_job is not None:
            # 다운로드 job 은 백그라운드에서 자체 종료 — 명시적 stop 안 함 (sub-thread 가 끊김
            # 어려운 hf snapshot_download 라). interpreter 종료 시 daemon 으로 같이 죽음.
            pass
