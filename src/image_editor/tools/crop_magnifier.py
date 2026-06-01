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
