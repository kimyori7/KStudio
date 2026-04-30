"""저장 / 파일명 설정 패널 — 이미지·영상 저장 폴더와 파일명 패턴.

(이름은 ScreenshotPanel 로 유지 — PreferencesDialog 호환. 실제 역할은 더 넓다.)
"""
from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QVBoxLayout,
    QFileDialog, QGroupBox, QComboBox,
)

from ...core.settings import (
    GeneralSettings,
    ScreenshotSettings,
    default_image_dir,
    default_video_dir,
)


_FORMAT_LABELS = [("png", "PNG")]


class ScreenshotPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, screenshot: ScreenshotSettings,
                 general: GeneralSettings | None = None):
        super().__init__()
        self.settings = screenshot          # 이미지 (스크린샷)
        self._general = general             # 영상 — 없으면 영상 섹션 숨김

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
        browse = QPushButton("📁")
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
        path = self._pick_directory(
            "이미지 저장 폴더", initial,
            name_filter="이미지 (*.png *.jpg *.jpeg *.bmp *.kstudio);;모든 파일 (*)",
        )
        if path:
            self.img_dir_edit.setText(path)
            self._sync()

    def _browse_video_dir(self) -> None:
        initial = self.vid_dir_edit.text().strip() or str(default_video_dir())
        Path(initial).mkdir(parents=True, exist_ok=True)
        path = self._pick_directory(
            "영상 저장 폴더", initial,
            name_filter="영상 (*.mp4 *.gif *.mkv *.mov *.webm);;모든 파일 (*)",
        )
        if path:
            self.vid_dir_edit.setText(path)
            self._sync()

    def _pick_directory(self, caption: str, initial: str, name_filter: str) -> str:
        # Qt 자체 다이얼로그를 써서 ShowDirsOnly 를 끔 — 폴더 안의 파일도 미리보기처럼
        # 보이도록(선택은 폴더 단위). Windows 네이티브 폴더 피커는 파일을 숨겨서
        # 사용자가 빈 폴더처럼 느끼는 문제 해결.
        dlg = QFileDialog(self, caption, initial)
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, False)
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setNameFilter(name_filter)
        dlg.setAcceptMode(QFileDialog.AcceptOpen)
        if dlg.exec() != QFileDialog.Accepted:
            return ""
        files = dlg.selectedFiles()
        if not files:
            return ""
        # 사용자가 파일을 선택해도 그 파일이 들어있는 폴더로 해석.
        chosen = Path(files[0])
        return str(chosen if chosen.is_dir() else chosen.parent)

    def _sync(self) -> None:
        self.settings.save_dir = self.img_dir_edit.text()
        self.settings.filename_pattern = self.img_pattern_edit.text()
        fmt = self.img_format_combo.currentData()
        if fmt:
            self.settings.format = fmt

        if self._general is not None:
            self._general.output_dir = self.vid_dir_edit.text()
            self._general.filename_pattern = self.vid_pattern_edit.text()

        self.settings_changed.emit()
