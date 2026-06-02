"""삭제(Del) 후 투명 영역 체커보드가 기본 배경 체커와 다르게 보이는 버그 재현.

시나리오:
  S1 (대조군): DPR 1.0 이미지 + 일부 알파 구멍 + 영역 삭제.
  S2 (가설):   devicePixelRatio=1.5 인 스크린샷류 이미지 + 영역 삭제.
               (Windows 150% 디스플레이 캡처 → QImage DPR 1.5)

각 경우 캔버스를 PNG 로 렌더하고, 파이프라인 경로(fast/clip)와
이미지/아이템/sceneRect 크기를 출력한다. settings 미사용.
"""
from __future__ import annotations
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem

from image_editor.layer_model import LayerStack
from image_editor.layers.image_layer import ImageLayer
from image_editor.canvas import LayerCanvas
from image_editor.selection import SelectionModel


def make_photo(w, h, dpr=1.0):
    """알파 구멍이 있는 사진. 왼쪽 절반 불투명 빨강, 오른쪽 위 1/4 투명(알파 구멍)."""
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#CC4433"))                       # 전체 불투명 빨강
    # 오른쪽 위 사분면을 투명으로 (기존 '기본 배경' 투명 영역을 만든다)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.fillRect(QRect(w // 2, 0, w - w // 2, h // 2), Qt.transparent)
    p.end()
    if dpr != 1.0:
        img.setDevicePixelRatio(dpr)
    return img


def build(photo: QImage):
    """from_screenshot 와 동일한 스택: 투명 배경 레이어 + 사진 레이어."""
    size = photo.size()                                # QImage.size() = device px
    stack = LayerStack(size)
    bg = QImage(size, QImage.Format_ARGB32)
    bg.fill(Qt.transparent)
    stack.add_layer(ImageLayer(id=1, name="배경", pixmap=bg))
    photo_layer = ImageLayer(id=2, name="사진", pixmap=photo)
    stack.add_layer(photo_layer)
    stack.set_active_layer(2)
    canvas = LayerCanvas(stack)
    return canvas, stack, photo_layer


def delete_region(stack, layer, rect: QRect):
    """edit_tab.delete_selection 의 핵심 로직을 그대로 모사."""
    local = QRect(rect)
    local.translate(-int(layer.offset.x()), -int(layer.offset.y()))
    new_pixmap = QImage(layer.pixmap).copy()
    p = QPainter(new_pixmap)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.fillRect(local, Qt.transparent)
    p.end()
    layer.pixmap = new_pixmap.copy()
    stack.notify_pixmap_changed(layer.id)


def diag(canvas, stack, layer, label):
    cs = stack.canvas_size
    item = None
    for it in canvas.scene().items():
        if isinstance(it, QGraphicsPixmapItem) and it.zValue() == 1:
            item = it
            break
    print(f"  [{label}] pixmap dev-size={layer.pixmap.width()}x{layer.pixmap.height()} "
          f"dpr={layer.pixmap.devicePixelRatio():.3g}  canvas_size(scene)={cs.width()}x{cs.height()}")
    if item is not None:
        br = item.boundingRect()
        pm = item.pixmap()
        print(f"        item pixmap dev-size={pm.width()}x{pm.height()} dpr={pm.devicePixelRatio():.3g} "
              f"-> boundingRect(scene)={br.width():.0f}x{br.height():.0f}")
        print(f"        sceneRect={canvas.scene().sceneRect().width():.0f}x{canvas.scene().sceneRect().height():.0f}")


def render_png(canvas, path):
    sr = canvas.scene().sceneRect()
    canvas.resize(int(sr.width()) + 4, int(sr.height()) + 4)
    canvas.show()
    QApplication.processEvents()
    img = QImage(canvas.viewport().size(), QImage.Format_ARGB32)
    img.fill(QColor("#101216"))
    p = QPainter(img)
    canvas.render(p)
    p.end()
    img.save(path)
    print(f"        saved {path}  ({img.width()}x{img.height()})")


def run(label, dpr, out_before, out_after):
    print(f"== {label} (dpr={dpr}) ==")
    photo = make_photo(160, 120, dpr=dpr)
    canvas, stack, layer = build(photo)
    diag(canvas, stack, layer, label + " BEFORE")
    render_png(canvas, out_before)
    # 가운데 가로 띠를 선택 후 삭제 (scene 좌표 = device px 기준)
    cs = stack.canvas_size
    rect = QRect(int(cs.width() * 0.15), int(cs.height() * 0.35),
                 int(cs.width() * 0.7), int(cs.height() * 0.3))
    print(f"        delete rect(scene)={rect.x(),rect.y(),rect.width(),rect.height()}")
    delete_region(stack, layer, rect)
    diag(canvas, stack, layer, label + " AFTER")
    render_png(canvas, out_after)
    print()


def main():
    QApplication.instance() or QApplication(sys.argv)
    here = os.path.dirname(__file__)
    run("S1-control", 1.0,
        os.path.join(here, "..", "diag_del_s1_before.png"),
        os.path.join(here, "..", "diag_del_s1_after.png"))
    run("S2-dpr1.5", 1.5,
        os.path.join(here, "..", "diag_del_s2_before.png"),
        os.path.join(here, "..", "diag_del_s2_after.png"))


if __name__ == "__main__":
    main()
