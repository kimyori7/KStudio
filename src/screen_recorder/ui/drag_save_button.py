"""드래그 가능한 저장 버튼 — 폴더에 드롭하면 현재 이미지 저장.

OS 의 파일 복사 메커니즘(QDrag + URL MIME)에 위임. 드래그 시작 시 임시 파일로
PNG 를 써두고 OS 가 그 경로를 복사하도록 한다.
"""
from __future__ import annotations
import tempfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDrag, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QPushButton


class DragSaveButton(QPushButton):
    """버튼 자체를 드래그 → 폴더에 놓으면 PNG 로 저장."""

    def __init__(self, parent=None) -> None:
        super().__init__("📤", parent)
        self.setToolTip("이 버튼을 드래그해서 폴더에 놓으면 이미지로 저장됩니다")
        self.setFixedWidth(36)
        self.image_provider: Callable[[], Optional[QImage]] = lambda: None
        self.filename_provider: Callable[[], str] = lambda: "image.png"
        self._press_pos: Optional[QPoint] = None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._press_pos is None:
            super().mouseMoveEvent(e)
            return
        if (e.position().toPoint() - self._press_pos).manhattanLength() < 8:
            super().mouseMoveEvent(e)
            return
        img = self.image_provider()
        if img is None or img.isNull():
            self._press_pos = None
            return
        # 임시 파일 작성
        fname = self.filename_provider() or "image.png"
        if not fname.lower().endswith(".png"):
            fname = Path(fname).stem + ".png"
        tmp_dir = Path(tempfile.gettempdir()) / "KStudio_drag"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / fname
        img.save(str(tmp_path), "PNG")
        # MIME 구성
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(tmp_path))])
        drag = QDrag(self)
        drag.setMimeData(md)
        thumb = QPixmap.fromImage(img.scaled(
            96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))
        drag.setPixmap(thumb)
        drag.setHotSpot(QPoint(thumb.width() // 2, thumb.height() // 2))
        drag.exec(Qt.CopyAction)
        self._press_pos = None

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(e)
