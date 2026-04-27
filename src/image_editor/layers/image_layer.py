"""ImageLayer — raster 픽셀 + 알파 마스크 + 캔버스 내 위치."""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter

from .base import Layer


def compose_image_with_mask(pixmap: QImage, mask: Optional[QImage]) -> QImage:
    """원본 + 알파 마스크 합성 결과를 새 ARGB32 QImage 로 반환.
    mask=None 이면 원본 그대로(ARGB32 변환).
    """
    out = pixmap.convertToFormat(QImage.Format_ARGB32)
    if mask is None:
        return out
    m = mask.convertToFormat(QImage.Format_Grayscale8)
    if m.size() != out.size():
        m = m.scaled(out.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    # 픽셀별 알파 곱
    for y in range(out.height()):
        for x in range(out.width()):
            argb = out.pixel(x, y)
            mv = m.pixel(x, y) & 0xFF  # gray = mask alpha
            a = ((argb >> 24) & 0xFF) * mv // 255
            out.setPixel(x, y, (a << 24) | (argb & 0x00FFFFFF))
    return out


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
