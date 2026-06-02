"""마술봉 미리보기 누적 버그 재현 진단.

시나리오: 빨강/초록/파랑 세 색 영역.
1. 빨강 영역 마술봉 클릭 → commit (layer.mask = 빨강=0)
2. 초록 영역 마술봉 클릭 → preview 계산
   → 기대: 미리보기 빨강 오버레이가 '초록' 영역에만 떠야 함.
   → 버그: 미리보기가 '빨강+초록' 둘 다 빨갛게 표시.

미리보기 이미지를 PNG 로 저장하고, 빨강 영역 / 초록 영역 각각에 미리보기
하이라이트(alpha>0) 픽셀이 몇 개인지 출력한다.
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# settings 보호 (혹시 import 사이드이펙트가 있어도 안전하게)
os.environ.setdefault("KSTUDIO_SETTINGS_DIR", os.path.join(os.environ.get("TEMP", "."), "kstudio_diag_settings"))

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from PySide6.QtGui import QGuiApplication, QImage, qRgba

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from image_editor.operations.magic_wand import compute_magic_wand_mask_with_rect
from image_editor.tools.magic_wand import _build_preview_image, _delta_preview_mask

W, H = 60, 20
# 세 개의 가로 띠가 아니라 세로 띠: 0~19=빨강, 20~39=초록, 40~59=파랑
img = QImage(W, H, QImage.Format_ARGB32)
for x in range(W):
    if x < 20:
        c = qRgba(230, 30, 30, 255)      # 빨강
    elif x < 40:
        c = qRgba(30, 200, 30, 255)      # 초록
    else:
        c = qRgba(30, 30, 230, 255)      # 파랑
    for y in range(H):
        img.setPixel(x, y, c)

RED_X, GREEN_X, MID_Y = 10, 30, 10
TOL = 30

# --- 1단계: 빨강 클릭 → mask1 (빨강=0) ---
mask1, aff1 = compute_magic_wand_mask_with_rect(img, None, RED_X, MID_Y, TOL)
print(f"[1] 빨강 클릭 affected bbox = {aff1}")

# commit 모사: layer.mask = mask1 (실제 MagicWandApplyCommand 가 하는 일)
committed_mask = mask1

# --- 2단계: 초록 클릭 → mask2 (기존 mask 위에 누적) ---
mask2, aff2 = compute_magic_wand_mask_with_rect(img, committed_mask, GREEN_X, MID_Y, TOL)
print(f"[2] 초록 클릭 affected bbox = {aff2}")

# 수정 후 동작 재현: 미리보기는 누적 마스크 전체가 아니라 이번 클릭의 delta 만.
preview = _build_preview_image(_delta_preview_mask(committed_mask, mask2))
preview.save(str(Path(__file__).resolve().parents[1] / "diag_magic_wand_preview.png"))


def count_highlight(qimg: QImage, x0: int, x1: int) -> int:
    """[x0, x1) 열 범위에서 alpha>0 인 미리보기 픽셀 수."""
    n = 0
    for x in range(x0, x1):
        for y in range(H):
            if (qimg.pixel(x, y) >> 24) & 0xFF:
                n += 1
    return n


red_hl = count_highlight(preview, 0, 20)
green_hl = count_highlight(preview, 20, 40)
blue_hl = count_highlight(preview, 40, 60)
print(f"[preview] 빨강영역 하이라이트 픽셀={red_hl}  초록영역={green_hl}  파랑영역={blue_hl}")
print()
if red_hl > 0:
    print(">>> 버그 확인: 이미 지운 '빨강' 영역이 초록 선택 미리보기에 다시 표시됨.")
else:
    print(">>> 정상: 미리보기가 새로 선택한 '초록' 영역에만 표시됨.")
