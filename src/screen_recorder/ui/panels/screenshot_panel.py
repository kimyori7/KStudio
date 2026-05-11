"""저장 / 파일명 설정 패널 — 이미지·영상 저장 폴더와 파일명 패턴.

(이름은 ScreenshotPanel 로 유지 — PreferencesDialog 호환. 실제 역할은 더 넓다.)
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QFileDialog, QGroupBox, QComboBox,
)

from ...core.settings import (
    GeneralSettings,
    PreferencesSettings,
    ScreenshotSettings,
    default_image_dir,
    default_video_dir,
)
from ...effects import default_sidecar_dir
from ..icons import load_icon


_FORMAT_LABELS = [("png", "PNG")]


class ScreenshotPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, screenshot: ScreenshotSettings,
                 general: GeneralSettings | None = None,
                 preferences: PreferencesSettings | None = None):
        super().__init__()
        self.settings = screenshot          # 이미지 (스크린샷)
        self._general = general             # 영상 — 없으면 영상 섹션 숨김
        self._preferences = preferences     # 사이드카 폴더 (편집본 .kstudio)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ---------- 이미지 저장 ----------
        img_box = QGroupBox("📸 이미지 저장")
        img_form = QFormLayout(img_box)
        img_form.setLabelAlignment(Qt.AlignRight)

        self.img_dir_edit, img_dir_row = self._make_dir_row(
            screenshot.save_dir, "_browse_image_dir"
        )
        self.img_dir_edit.setPlaceholderText(
            f"기본값: {default_image_dir()}"
        )
        img_form.addRow("저장 폴더:", img_dir_row)

        self.img_pattern_edit = QLineEdit(screenshot.filename_pattern)
        self.img_pattern_edit.setToolTip(
            "사용 가능 토큰: {date}, {time}, {datetime}, {target}, {mode} 등"
        )
        img_form.addRow("파일명:", self.img_pattern_edit)

        self.img_format_combo = QComboBox()
        for key, label in _FORMAT_LABELS:
            self.img_format_combo.addItem(label, key)
        cur = screenshot.format
        for i in range(self.img_format_combo.count()):
            if self.img_format_combo.itemData(i) == cur:
                self.img_format_combo.setCurrentIndex(i)
                break
        img_form.addRow("형식:", self.img_format_combo)

        root.addWidget(img_box)

        # ---------- 영상 저장 ----------
        if general is not None:
            vid_box = QGroupBox("🎞 영상 저장")
            vid_form = QFormLayout(vid_box)
            vid_form.setLabelAlignment(Qt.AlignRight)

            self.vid_dir_edit, vid_dir_row = self._make_dir_row(
                general.output_dir, "_browse_video_dir"
            )
            self.vid_dir_edit.setPlaceholderText(
                f"기본값: {default_video_dir()}"
            )
            vid_form.addRow("저장 폴더:", vid_dir_row)

            self.vid_pattern_edit = QLineEdit(general.filename_pattern)
            self.vid_pattern_edit.setToolTip(
                "사용 가능 토큰: {date}, {time}, {datetime}, {target}, {mode} 등"
            )
            vid_form.addRow("파일명:", self.vid_pattern_edit)

            # 편집본(.kstudio 사이드카) 저장 폴더 — preferences.sidecar_dir.
            if self._preferences is not None:
                self.sidecar_dir_edit, sc_dir_row = self._make_dir_row(
                    self._preferences.sidecar_dir, "_browse_sidecar_dir"
                )
                self.sidecar_dir_edit.setPlaceholderText(
                    f"기본값: {default_sidecar_dir()}"
                )
                self.sidecar_dir_edit.setToolTip(
                    "영상 편집본(.kstudio) 사이드카 저장 폴더. 비워두면 OS 기본 위치 사용."
                )
                vid_form.addRow("편집본 폴더:", sc_dir_row)
                self.sidecar_dir_edit.editingFinished.connect(self._sync)

            root.addWidget(vid_box)

            self.vid_dir_edit.editingFinished.connect(self._sync)
            self.vid_pattern_edit.editingFinished.connect(self._sync)

        root.addStretch(1)

        # ---------- 시그널 ----------
        self.img_dir_edit.editingFinished.connect(self._sync)
        self.img_pattern_edit.editingFinished.connect(self._sync)
        self.img_format_combo.currentIndexChanged.connect(self._sync)

    # ---------- helper ----------

    def _make_dir_row(self, initial: str, browse_method: str):
        edit = QLineEdit(initial)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton()
        browse.setIcon(load_icon("folder", size=18))
        browse.setIconSize(QSize(18, 18))
        browse.setToolTip("폴더 선택…")
        browse.setFixedWidth(36)
        browse.clicked.connect(getattr(self, browse_method))
        layout.addWidget(edit, stretch=1)
        layout.addWidget(browse)
        return edit, row

    def _browse_image_dir(self) -> None:
        # 입력란이 비어있으면 기본 저장 폴더 (~/KStudio/Image) 부터 보이게 — Path.home()
        # 으로 떨어지면 사용자가 매번 KStudio 폴더로 이동해야 함. 폴더가 없으면 미리 생성.
        initial = self.img_dir_edit.text().strip() or str(default_image_dir())
        Path(initial).mkdir(parents=True, exist_ok=True)
        path = self._pick_directory_native("이미지 저장 폴더", initial)
        if path:
            self.img_dir_edit.setText(path)
            self._sync()

    def _browse_video_dir(self) -> None:
        initial = self.vid_dir_edit.text().strip() or str(default_video_dir())
        Path(initial).mkdir(parents=True, exist_ok=True)
        path = self._pick_directory_native("영상 저장 폴더", initial)
        if path:
            self.vid_dir_edit.setText(path)
            self._sync()

    def _browse_sidecar_dir(self) -> None:
        initial = self.sidecar_dir_edit.text().strip() or str(default_sidecar_dir())
        Path(initial).mkdir(parents=True, exist_ok=True)
        path = self._pick_directory_native("편집본(.kstudio) 저장 폴더", initial)
        if path:
            self.sidecar_dir_edit.setText(path)
            self._sync()

    def _pick_directory_native(self, caption: str, initial: str) -> str:
        """Windows 네이티브 폴더 picker. 윈도우 탐색기 UX 그대로:
        - 주소 표시줄에 경로 직접 입력 / Ctrl+V 로 paste 가능
        - 좌측 트리에서 폴더 선택, 상단 주소창에서 전체 경로 선택·복사 가능

        이미지/영상/편집본 셋 다 동일 패턴. 폴더 안 파일 미리보기는 native 다이얼로그
        도 좌측 트리 + 우측 폴더 내용 표시로 충분 (사용자 결정 2026-05-11).
        """
        return QFileDialog.getExistingDirectory(
            self, caption, initial, QFileDialog.ShowDirsOnly,
        )

    def _sync(self) -> None:
        self.settings.save_dir = self.img_dir_edit.text()
        self.settings.filename_pattern = self.img_pattern_edit.text()
        fmt = self.img_format_combo.currentData()
        if fmt:
            self.settings.format = fmt

        if self._general is not None:
            self._general.output_dir = self.vid_dir_edit.text()
            self._general.filename_pattern = self.vid_pattern_edit.text()

        if self._preferences is not None and hasattr(self, "sidecar_dir_edit"):
            self._preferences.sidecar_dir = self.sidecar_dir_edit.text()

        self.settings_changed.emit()
