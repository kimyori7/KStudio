"""CropMagnifier — 크롭 도구 전용 확대경 위젯 (120x120 @ 고정 8x).

영역 스크린샷의 Magnifier 를 본떴으나 image_editor 패키지 안에 독립 구현한다
(image_editor 는 screen_recorder 를 import 하지 않는 단방향 의존 구조). 배율은
캔버스 줌과 무관한 절대값이라 4K·소형 이미지에서 항상 같은 픽셀 이웃을 같은 크기로
보여준다 ("픽셀 단위로 보기" / "동일한 정도" 요구 충족).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QWidget

LENS_SIZE = 120              # 렌즈 한 변(px)
ZOOM = 8                     # 고정 확대 배율(원본 1픽셀 = 8x8 블록). 진단 PNG 로 미세조정.
SRC_SIZE = LENS_SIZE // ZOOM  # 렌즈에 담는 원본 픽셀 한 변(=15)
LABEL_HEIGHT = 34            # 2줄 라벨 높이
MAG_W = LENS_SIZE
MAG_H = LENS_SIZE + LABEL_HEIGHT
_MAG_OFFSET = 24             # 커서로부터 돋보기 좌상단 오프셋


def effective_src_size(img_w: int, img_h: int) -> int:
    """렌즈가 샘플링할 원본 픽셀 한 변. 이미지가 SRC_SIZE 보다 작으면 그만큼, 최소 1."""
    return max(1, min(SRC_SIZE, img_w, img_h))


def clamp_src_origin(center_x: int, center_y: int, src_size: int,
                     img_w: int, img_h: int) -> tuple[int, int]:
    """src_rect 좌상단을 이미지 경계 안으로 클램프."""
    sx = center_x - src_size // 2
    sy = center_y - src_size // 2
    sx = max(0, min(sx, img_w - src_size))
    sy = max(0, min(sy, img_h - src_size))
    return sx, sy


def loupe_position(vp_x: int, vp_y: int, vp_w: int, vp_h: int,
                   mag_w: int = MAG_W, mag_h: int = MAG_H,
                   offset: int = _MAG_OFFSET) -> tuple[int, int]:
    """커서(뷰포트 좌표) 기준 돋보기 좌상단. 뷰포트 오른쪽/아래 가장자리에서 반대쪽 플립."""
    mx = vp_x + offset
    my = vp_y + offset
    if mx + mag_w > vp_w:
        mx = vp_x - offset - mag_w
    if my + mag_h > vp_h:
        my = vp_y - offset - mag_h
    return max(0, mx), max(0, my)


class CropMagnifier(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 클릭/드래그 통과
        self.setFixedSize(MAG_W, MAG_H)
        self._source: QImage | None = None
        self._center: QPoint = QPoint(0, 0)
        self._rect_size: QSize | None = None

    def set_source(self, img: QImage) -> None:
        self._source = img

    def update_at(self, center_img: QPoint, rect_size: QSize | None) -> None:
        """center_img: 커서의 이미지 픽셀 좌표(=scene 좌표). rect_size: 현재 크롭 크기(없으면 None)."""
        self._center = QPoint(center_img)
        self._rect_size = QSize(rect_size) if rect_size is not None else None
        self.update()

    def _coord_text(self) -> str:
        return f"X: {self._center.x()}  Y: {self._center.y()}"

    def _size_text(self) -> str:
        if self._rect_size is None:
            return "—"
        return f"{self._rect_size.width()} × {self._rect_size.height()}"

    def paintEvent(self, _):
        p = QPainter(self)
        lens_rect = QRect(0, 0, LENS_SIZE, LENS_SIZE)
        p.fillRect(lens_rect, QColor(20, 20, 20))
        # 확대 영역 — painter 에 SmoothPixmapTransform 미설정 → nearest-neighbor(픽셀 또렷)
        if self._source is not None and not self._source.isNull():
            ss = effective_src_size(self._source.width(), self._source.height())
            sx, sy = clamp_src_origin(self._center.x(), self._center.y(), ss,
                                      self._source.width(), self._source.height())
            p.drawImage(lens_rect, self._source, QRect(sx, sy, ss, ss))
        cx = LENS_SIZE // 2
        cy = LENS_SIZE // 2
        # 십자선(노랑)
        p.setPen(QPen(QColor(255, 190, 0), 1))
        p.drawLine(cx, 0, cx, LENS_SIZE)
        p.drawLine(0, cy, LENS_SIZE, cy)
        # 중앙 픽셀 박스(빨강) — 한 변 = ZOOM px = 원본 1픽셀
        p.setPen(QPen(QColor(255, 50, 50), 1))
        p.drawRect(cx - ZOOM // 2, cy - ZOOM // 2, ZOOM, ZOOM)
        # 테두리(노랑)
        p.setPen(QPen(QColor(255, 190, 0), 2))
        p.drawRect(lens_rect.adjusted(0, 0, -1, -1))
        # 라벨 2줄
        label_rect = QRect(0, LENS_SIZE, MAG_W, LABEL_HEIGHT)
        p.fillRect(label_rect, QColor(0, 0, 0, 200))
        p.setPen(QColor(255, 255, 255))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        line_h = LABEL_HEIGHT // 2
        p.drawText(QRect(0, LENS_SIZE, MAG_W, line_h), Qt.AlignCenter, self._coord_text())
        p.drawText(QRect(0, LENS_SIZE + line_h, MAG_W, line_h), Qt.AlignCenter, self._size_text())
