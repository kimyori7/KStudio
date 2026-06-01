"""compute_trim_rect — 가장자리 균일색/투명 여백을 감지해 내용물 바운딩박스를 반환.

순수 함수(QImage → QRect|None). GUI 의존 없음. 실제 자르기는 CropCommand 가 담당.
반환 QRect 는 입력 이미지와 동일한 좌표계(= canvas.composite() 좌표) → CropCommand 직투입.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

_CORNER = 5  # 코너 샘플 패치 한 변 (px)


def _to_bgra(image: QImage) -> np.ndarray:
    """QImage → (h, w, 4) uint8 numpy 배열. 채널 순서 B,G,R,A (ARGB32 little-endian).

    ⚠ 반드시 .copy() — numpy view 는 로컬 QImage(img) 버퍼를 가리키므로, 복사 없이
    반환하면 함수 종료 시 img 가 GC 되어 freed 메모리를 읽는 dangling 버그가 난다.
    """
    img = image.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    # bytesPerLine stride 를 따라 reshape — packed(w*4) 가정 금지(padded stride 대응).
    return (
        np.frombuffer(img.constBits(), dtype=np.uint8)
        .reshape(h, img.bytesPerLine())[:, : w * 4]
        .reshape(h, w, 4)
        .copy()
    )


def compute_trim_rect(
    image: QImage,
    *,
    tolerance: int = 12,
    min_bg_fraction: float = 0.99,
) -> Optional[QRect]:
    """가장자리의 균일한 배경 여백을 제거한 내용물 바운딩박스.

    - tolerance: 채널별(0~255) 허용오차. 클수록 더 너그럽게 배경으로 인정.
    - min_bg_fraction: 한 줄(행/열)을 '배경 줄'로 인정하는 배경 픽셀 비율.
    반환 None: 균일 테두리 없음 / 전체가 배경 / 자를 여백 없음.
    """
    if image.isNull():
        return None
    h, w = image.height(), image.width()
    if w < 2 or h < 2:
        return None

    buf = _to_bgra(image)  # (h, w, 4) uint8 — 아래 buf - bg 에서 float 로 승격돼 부호 안전.
    c = min(_CORNER, w, h)
    corners = [
        buf[0:c, 0:c],
        buf[0:c, w - c : w],
        buf[h - c : h, 0:c],
        buf[h - c : h, w - c : w],
    ]
    # 각 코너 대표색 = 채널별 중앙값 (단일 픽셀 노이즈/안티앨리어싱에 강함)
    corner_meds = np.array([np.median(p.reshape(-1, 4), axis=0) for p in corners])  # (4,4)

    # 균일성 게이트 — 코너 간 채널별 최대 편차가 tolerance 초과면 균일 테두리 아님.
    spread = corner_meds.max(axis=0) - corner_meds.min(axis=0)
    if np.any(spread > tolerance):
        return None
    bg = np.median(corner_meds, axis=0)  # (4,) 배경색

    # 배경 마스크: 모든 채널(알파 포함)이 tolerance 이내.
    is_bg = np.all(np.abs(buf - bg) <= tolerance, axis=2)  # (h, w) bool

    row_bg = is_bg.mean(axis=1) >= min_bg_fraction  # (h,)
    col_bg = is_bg.mean(axis=0) >= min_bg_fraction  # (w,)

    top = 0
    while top < h and row_bg[top]:
        top += 1
    if top >= h:
        return None  # 전체가 배경
    bottom = h - 1
    while bottom > top and row_bg[bottom]:
        bottom -= 1
    left = 0
    while left < w and col_bg[left]:
        left += 1
    if left >= w:
        return None
    right = w - 1
    while right > left and col_bg[right]:
        right -= 1

    new_w = right - left + 1
    new_h = bottom - top + 1
    if new_w >= w and new_h >= h:
        return None  # 자를 여백 없음
    return QRect(int(left), int(top), int(new_w), int(new_h))
