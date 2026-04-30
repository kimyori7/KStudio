"""ImageLayer — raster 픽셀 + 알파 마스크 + 캔버스 내 위치."""
from __future__ import annotations
from typing import Optional

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter

from .base import Layer


def compose_image_with_mask(pixmap: QImage, mask: Optional[QImage]) -> QImage:
    """원본 + 알파 마스크 합성 결과를 새 ARGB32 QImage 로 반환.
    mask=None 이면 원본 그대로(ARGB32 변환).

    마스크 브러시·자동 누끼 결과가 캔버스 새로 그릴 때마다 호출되므로 numpy 로
    벡터화 — 1080p 한 장에 수 ms. (이전 픽셀 루프는 1080p 에서 수 초 소요)
    """
    out = pixmap.convertToFormat(QImage.Format_ARGB32)
    if mask is None:
        return out
    m = mask.convertToFormat(QImage.Format_Grayscale8)
    if m.size() != out.size():
        m = m.scaled(out.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    w, h = out.width(), out.height()
    out_buf = np.frombuffer(out.constBits(), dtype=np.uint8).reshape(h, out.bytesPerLine())[:, : w * 4].reshape(h, w, 4).copy()
    mask_buf = np.frombuffer(m.constBits(), dtype=np.uint8).reshape(h, m.bytesPerLine())[:, :w]
    # ARGB32 little-endian: byte order in memory = B,G,R,A → 알파는 index 3
    alpha = out_buf[:, :, 3].astype(np.uint16)
    new_alpha = (alpha * mask_buf.astype(np.uint16) // 255).astype(np.uint8)
    out_buf[:, :, 3] = new_alpha
    result = QImage(out_buf.tobytes(), w, h, w * 4, QImage.Format_ARGB32).copy()
    return result


class ImageLayer(Layer):
    def __init__(
        self, id: int, name: str, *,
        pixmap: QImage,
        mask: Optional[QImage] = None,
        offset: QPoint = QPoint(0, 0),
        visible: bool = True,
        opacity: float = 1.0,
    ) -> None:
        super().__init__(id, name, visible=visible, opacity=opacity)
        self.pixmap = pixmap.convertToFormat(QImage.Format_ARGB32)
        self.mask = mask
        self.offset = QPoint(offset)

    def composed_pixmap(self) -> QImage:
        """pixmap × mask (캔버스 합성 전 단일 레이어 이미지)."""
        return compose_image_with_mask(self.pixmap, self.mask)

    def render(self, canvas_size: QSize) -> QImage:
        out = QImage(canvas_size, QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.setOpacity(self.opacity)
            painter.drawImage(self.offset, self.composed_pixmap())
        finally:
            painter.end()
        return out

    def apply_crop(self, rect: QRect) -> None:
        # canvas_size 가 rect.size 로 바뀌면 레이어의 offset 도 그만큼 이동
        self.offset = QPoint(self.offset.x() - rect.x(), self.offset.y() - rect.y())
