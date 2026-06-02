"""크롭 돋보기 '가장자리 추적' 진단.

사용자 보고: 커서가 이미지 끝쯤 갈 때 돋보기 줌이 더 이상 안 따라감.
커서를 이미지 안 → 가장자리 → 바깥(음수 scene 좌표)으로 이동시키며
돋보기 내용(content)이 따라오는지 PNG 로 확인한다.

실행: python scripts/diagnose_crop_magnifier_edge.py
출력: diag_crop_magnifier/edge_*.png
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from image_editor.tools.crop_magnifier import CropMagnifier


def _grid_image(w: int, h: int) -> QImage:
    """10px 격자 + 좌상단 모서리 표식 — 어느 픽셀을 보고 있는지 또렷하게."""
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setPen(QColor("#3060C0"))
    for x in range(0, w, 10):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 10):
        p.drawLine(0, y, w, y)
    # 좌상단 10x10 빨강 — 모서리 확인용
    p.fillRect(0, 0, 10, 10, QColor("#D03030"))
    p.end()
    return img


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = os.path.join(os.path.dirname(__file__), "..", "diag_crop_magnifier")
    os.makedirs(out_dir, exist_ok=True)

    img = _grid_image(300, 300)
    mag = CropMagnifier()
    mag.set_source(img)
    mag.resize(mag.size())
    mag.show()
    app.processEvents()

    # 커서: 안쪽 → 가장자리 → 바깥(음수). content 가 따라오면 보이는 모서리가 점점 이동해야 함.
    for cx, cy in [(50, 50), (20, 20), (8, 8), (4, 4), (0, 0), (-12, -13), (-40, -40)]:
        mag.update_at(QPoint(cx, cy), QSize(40, 30))
        app.processEvents()
        path = os.path.join(out_dir, f"edge_{cx}_{cy}.png".replace("-", "m"))
        mag.grab().save(path)
        print(path)
    print("done")


if __name__ == "__main__":
    main()
