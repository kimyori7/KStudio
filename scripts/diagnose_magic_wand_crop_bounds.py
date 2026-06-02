"""마술봉이 크롭 경계 밖으로 번지는 버그 재현/검증 진단 (사용자 보고 2026-06-02).

시나리오:
- 원본 60x20 흰색. 좌우 15px 씩 잘라낸 크롭을 모사 (offset=(-15,0), canvas=30x20).
- 캔버스 중앙을 마술봉으로 클릭.
- 크롭은 lazy 라 pixmap 은 원본 60px 그대로 → 색이 균일하면 flood 가 캔버스 밖
  (잘려나간 좌우 테두리)까지 번진다.

좌/우 두 패널을 한 PNG 로 저장:
  좌 = bounds 없음 (옛 동작, 버그) — 빨강 오버레이가 캔버스(초록 테두리) 밖까지 참.
  우 = bounds = 캔버스 창 (수정 후) — 빨강 오버레이가 캔버스 안에만 머묾.
캔버스 영역은 초록 테두리로 표시.
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "KSTUDIO_SETTINGS_DIR",
    os.path.join(os.environ.get("TEMP", "."), "kstudio_diag_settings"),
)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

app = QGuiApplication.instance() or QGuiApplication(sys.argv)

from image_editor.operations.magic_wand import compute_magic_wand_mask_with_rect
from image_editor.tools.magic_wand import _build_preview_image, _delta_preview_mask

ORIG_W, ORIG_H = 60, 20
CROP = QRect(15, 0, 30, ORIG_H)          # 좌우 15px 제거 → 캔버스 30x20
OFFSET = QPoint(-CROP.x(), -CROP.y())     # apply_crop 후 레이어 offset
CLICK_LOCAL_X = 30                        # 캔버스 중앙(scene x=15) → local x=30
CLICK_Y = 10
TOL = 20
SCALE = 6                                 # PNG 보기 좋게 확대

full = QImage(ORIG_W, ORIG_H, QImage.Format_ARGB32)
full.fill(QColor(255, 255, 255, 255))


# 뷰포트(scene) 공간으로 렌더 — 사용자가 실제로 보는 화면. scene 좌표 s → 패널 s+MARGIN.
# 캔버스 밖(잘려나간 영역)을 볼 수 있도록 좌우/상하 여백을 둔다.
MARGIN = 15
PANEL_W = CROP.width() + MARGIN * 2
PANEL_H = ORIG_H + MARGIN * 2


def render_panel(bounds: QRect | None) -> tuple[QImage, str]:
    new_mask, affected = compute_magic_wand_mask_with_rect(
        full, None, CLICK_LOCAL_X, CLICK_Y, TOL, bounds=bounds,
    )
    overlay = _build_preview_image(_delta_preview_mask(None, new_mask))

    panel = QImage(PANEL_W, PANEL_H, QImage.Format_ARGB32)
    panel.fill(QColor(45, 50, 56))                    # 캔버스 밖 = 뷰포트 회색 배경
    p = QPainter(panel)
    try:
        m = QPoint(MARGIN, MARGIN)
        # 캔버스(크롭 후 = scene 0..canvas) 흰 배경
        p.fillRect(QRect(MARGIN, MARGIN, CROP.width(), CROP.height()),
                   QColor(255, 255, 255))
        # 레이어 pixmap/overlay 는 scene 에서 offset 위치에 그려진다 (캔버스에 클립 안 됨).
        p.drawImage(OFFSET + m, overlay)              # 빨강 미리보기
        # 캔버스 경계 초록 테두리
        p.setPen(QColor(0, 220, 0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRect(MARGIN, MARGIN, CROP.width() - 1, CROP.height() - 1))
    finally:
        p.end()
    return panel, "affected=%s" % (affected,)


before, before_lbl = render_panel(None)
after, after_lbl = render_panel(QRect(-OFFSET.x(), -OFFSET.y(), CROP.width(), CROP.height()))

gap = 8
out = QImage(PANEL_W * 2 + gap, PANEL_H, QImage.Format_ARGB32)
out.fill(QColor(0, 0, 0))
p = QPainter(out)
try:
    p.drawImage(0, 0, before)
    p.drawImage(PANEL_W + gap, 0, after)
finally:
    p.end()
out = out.scaled(out.width() * SCALE, out.height() * SCALE, Qt.IgnoreAspectRatio, Qt.FastTransformation)
dest = Path(__file__).resolve().parents[1] / "diag_magic_wand_crop_bounds.png"
out.save(str(dest))

print(f"좌(버그, bounds=None):  {before_lbl}")
print(f"우(수정, bounds=캔버스창): {after_lbl}")
print(f"캔버스 창(layer-local) = {QRect(-OFFSET.x(), -OFFSET.y(), CROP.width(), CROP.height())}")
print(f"PNG 저장: {dest}")
