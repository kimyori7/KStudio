"""클립보드 MimeData → QImage (캔버스 붙여넣기용).

우선순위: ① 클립보드의 이미지 데이터(앱 내부 복사·캡처·스크린샷). 없으면
② 클립보드의 파일 URL 중 첫 이미지 파일(탐색기에서 PNG 등 복사 → 붙여넣기). 둘 다
없으면 null QImage 반환 → 호출자가 no-op.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage

# 파일 URL 폴백에서 시도할 확장자 (대소문자 무시).
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def image_from_clipboard(mime: QMimeData | None) -> QImage:
    if mime is None:
        return QImage()

    if mime.hasImage():
        img = QImage(mime.imageData())
        if not img.isNull():
            return img

    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() not in _IMAGE_EXTS:
                continue
            img = QImage(path)
            if not img.isNull():
                return img

    return QImage()
