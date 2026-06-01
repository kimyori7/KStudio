"""크롭 돋보기 시각 진단 — 4K·소형 이미지 × 여러 줌에서 PNG 캡처.

실행: python scripts/diagnose_crop_magnifier.py
출력: diag_crop_magnifier/*.png (생성된 경로 stdout 출력)
설정 폴더를 건드리지 않음(메인 윈도우 미사용 — LayerCanvas 만 직접 구성).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from image_editor.layer_model import LayerStack
from image_editor.layers.image_layer import ImageLayer
from image_editor.canvas import LayerCanvas
from image_editor.tools.crop import CropTool


def _grid_image(w: int, h: int) -> QImage:
    """10px 격자 + 대각선 — 픽셀 또렷함/배율을 눈으로 확인하기 좋은 패턴."""
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setPen(QColor("#3060C0"))
    for x in range(0, w, 10):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 10):
        p.drawLine(0, y, w, y)
    p.setPen(QColor("#D03030"))
    p.drawLine(0, 0, w, h)
    p.end()
    return img


def _capture(app, out_dir, label, img_w, img_h, zoom, cursor):
    stack = LayerStack(QSize(img_w, img_h))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_grid_image(img_w, img_h)))
    canvas = LayerCanvas(stack)
    canvas.resize(800, 600)
    canvas.show()
    app.processEvents()
    canvas.set_zoom_factor(zoom)
    tool = CropTool()
    canvas.set_tool(tool)
    # hover 로 돋보기 표시 + 약간의 드래그로 크기 라벨도 노출
    tool.mouse_press(canvas.scene(), QPointF(cursor[0] - 12, cursor[1] - 9))
    tool.mouse_move(canvas.scene(), QPointF(*cursor))
    app.processEvents()
    path = os.path.join(out_dir, f"{label}.png")
    canvas.grab().save(path)
    print(path)
    canvas.set_tool(None)
    canvas.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = os.path.join(os.path.dirname(__file__), "..", "diag_crop_magnifier")
    os.makedirs(out_dir, exist_ok=True)
    # 소형 300x300 — 100%
    _capture(app, out_dir, "small_100", 300, 300, 1.0, (150, 150))
    # 4K 3840x2160 — 25%(fit 느낌) / 100%
    # 100% 에선 뷰포트(800x600)에 좌상단 일부만 보이므로 커서를 보이는 영역 안에 둔다.
    _capture(app, out_dir, "4k_25", 3840, 2160, 0.25, (1920, 1080))
    _capture(app, out_dir, "4k_100", 3840, 2160, 1.0, (400, 300))
    print("done")


if __name__ == "__main__":
    main()
