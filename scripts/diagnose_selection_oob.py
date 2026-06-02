"""영역 선택(SelectionTool) 이 이미지(=캔버스 sceneRect) 밖으로 나가는지 재현.

여러 시나리오로 드래그를 흉내내고, 결과 model.rect() 가 sceneRect 안에
머무는지 검사한다. 또 캔버스를 PNG 로 렌더해 눈으로 확인한다.

순수 image_editor + PySide6 만 사용 — settings 를 건드리지 않음.
"""
from __future__ import annotations
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from image_editor.layer_model import LayerStack
from image_editor.layers.image_layer import ImageLayer
from image_editor.canvas import LayerCanvas
from image_editor.selection import SelectionModel
from image_editor.tools.selection import SelectionTool
from PySide6.QtCore import QSize


def _solid(w, h, color="#CC3333"):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


def _build(cw, ch, iw, ih, ix=0, iy=0):
    """캔버스 cw×ch, 그 안에 iw×ih 이미지를 (ix,iy) 에 놓는다 (offset 으로 여백)."""
    stack = LayerStack(QSize(cw, ch))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(iw, ih))
    try:
        layer.offset = layer.offset.__class__(ix, iy)
    except Exception:
        pass
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    canvas.resize(cw + 40, ch + 40)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = SelectionTool(model)
    canvas.set_tool(tool)
    return canvas, model, tool, stack


def _check(name, model, scene_rect):
    r = model.rect()
    if r is None:
        print(f"  [{name}] rect=None")
        return
    rf = QRectF(r)
    inside = scene_rect.contains(rf)
    flag = "OK " if inside else "*** OUT OF BOUNDS ***"
    print(f"  [{name}] rect={r.x(),r.y(),r.width(),r.height()}  sceneRect="
          f"{int(scene_rect.x()),int(scene_rect.y()),int(scene_rect.width()),int(scene_rect.height())}  {flag}")


def scenario_drag_out(canvas, model, tool, label):
    sr = canvas.scene().sceneRect()
    # 안에서 눌러 밖(좌상단 음수)으로 드래그
    tool.mouse_press(canvas.scene(), QPointF(sr.width() * 0.6, sr.height() * 0.6))
    tool.mouse_move(canvas.scene(), QPointF(-200, -200))
    tool.mouse_release(canvas.scene(), QPointF(-200, -200))
    _check(label + " drag↖out", model, sr)


def scenario_drag_out_br(canvas, model, tool, label):
    sr = canvas.scene().sceneRect()
    tool.mouse_press(canvas.scene(), QPointF(sr.width() * 0.4, sr.height() * 0.4))
    tool.mouse_move(canvas.scene(), QPointF(sr.width() + 500, sr.height() + 500))
    tool.mouse_release(canvas.scene(), QPointF(sr.width() + 500, sr.height() + 500))
    _check(label + " drag↘out", model, sr)


def scenario_handle_out(canvas, model, tool, label):
    sr = canvas.scene().sceneRect()
    from PySide6.QtCore import QRect
    # 캔버스를 거의 다 덮는 선택을 먼저 만든 뒤, 좌상단 핸들을 음수로 끌기
    model.set_rect(QRect(2, 2, int(sr.width()) - 4, int(sr.height()) - 4))
    tool.mouse_press(canvas.scene(), QPointF(2, 2))    # NW 핸들
    tool.mouse_move(canvas.scene(), QPointF(-300, -300))
    tool.mouse_release(canvas.scene(), QPointF(-300, -300))
    _check(label + " handle↖out", model, sr)


def scenario_inside_drag_out(canvas, model, tool, label):
    sr = canvas.scene().sceneRect()
    from PySide6.QtCore import QRect
    model.set_rect(QRect(int(sr.width()*0.3), int(sr.height()*0.3),
                         int(sr.width()*0.4), int(sr.height()*0.4)))
    cx = sr.width()*0.5; cy = sr.height()*0.5
    tool.mouse_press(canvas.scene(), QPointF(cx, cy))   # inside
    tool.mouse_move(canvas.scene(), QPointF(cx - 1000, cy - 1000))
    tool.mouse_release(canvas.scene(), QPointF(cx - 1000, cy - 1000))
    _check(label + " inside-drag-out", model, sr)


def render_png(canvas, model, path):
    """현재 selection 을 가진 캔버스를 뷰포트 기준으로 PNG 렌더."""
    canvas.show()
    QApplication.processEvents()
    img = QImage(canvas.viewport().size(), QImage.Format_ARGB32)
    img.fill(QColor("#101216"))
    p = QPainter(img)
    canvas.render(p)
    p.end()
    img.save(path)
    print(f"  saved {path}")


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    print("== 시나리오 A: 캔버스 == 이미지 (100x80, 여백 없음) ==")
    for fn in (scenario_drag_out, scenario_drag_out_br, scenario_handle_out, scenario_inside_drag_out):
        canvas, model, tool, stack = _build(100, 80, 100, 80)
        fn(canvas, model, tool, "A")

    print("\n== 시나리오 B: 캔버스 > 이미지 (캔버스 200x140, 이미지 100x40 @ (50,50)) ==")
    for fn in (scenario_drag_out, scenario_drag_out_br):
        canvas, model, tool, stack = _build(200, 140, 100, 40, 50, 50)
        fn(canvas, model, tool, "B")

    print("\n== 시나리오 C: 줌 2x 상태에서 드래그 아웃 ==")
    canvas, model, tool, stack = _build(100, 80, 100, 80)
    canvas.set_zoom(2.0)
    scenario_drag_out(canvas, model, tool, "C(zoom2)")
    canvas2, model2, tool2, _ = _build(100, 80, 100, 80)
    canvas2.set_zoom(2.0)
    scenario_drag_out_br(canvas2, model2, tool2, "C(zoom2)")

    print("\n== 시나리오 D: 선택 후 캔버스 축소 (crop/undo 흉내) — 재클램프 누락? ==")
    from PySide6.QtCore import QRect, QSize as _QSize
    canvas, model, tool, stack = _build(200, 140, 200, 140)
    model.set_rect(QRect(20, 20, 160, 100))   # 큰 캔버스 안에서 선택
    _check("D 축소 전", model, canvas.scene().sceneRect())
    stack.set_canvas_size(_QSize(100, 80))     # crop 등으로 캔버스 축소
    QApplication.processEvents()
    _check("D 축소 후", model, canvas.scene().sceneRect())
    render_png(canvas, model, os.path.join(os.path.dirname(__file__), "..", "diag_selection_D_shrunk.png"))

    print("\n== 시나리오 E (H1): 불투명 내용이 캔버스 하단 band, 위는 투명 — 선택을 위에서 그림 ==")
    from PySide6.QtCore import QRect
    # 넓고 낮은 캔버스, 빨간 막대는 하단 band 에만 (위는 투명 = 체커보드)
    cw, ch = 600, 200
    img = QImage(cw, ch, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))           # 전부 투명
    p = QPainter(img)
    p.fillRect(QRect(40, 130, cw - 80, 40), QColor("#E0402C"))  # 하단 빨간 막대
    p.end()
    stack = LayerStack(QSize(cw, ch))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=img))
    canvas = LayerCanvas(stack)
    canvas.resize(cw + 40, ch + 40)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = SelectionTool(model)
    canvas.set_tool(tool)
    # 캔버스 위쪽(투명 영역)부터 막대 근처까지 드래그 — 클램프돼도 sceneRect 안.
    tool.mouse_press(canvas.scene(), QPointF(40, 20))
    tool.mouse_move(canvas.scene(), QPointF(cw - 100, 150))
    tool.mouse_release(canvas.scene(), QPointF(cw - 100, 150))
    _check("E(H1) 투명-위 선택", model, canvas.scene().sceneRect())
    render_png(canvas, model, os.path.join(os.path.dirname(__file__), "..", "diag_selection_E_h1.png"))

    print("\n== PNG 렌더 (시나리오 A drag↘out 후) ==")
    canvas, model, tool, stack = _build(100, 80, 100, 80)
    scenario_drag_out_br(canvas, model, tool, "A-png")
    render_png(canvas, model, os.path.join(os.path.dirname(__file__), "..", "diag_selection_A.png"))


if __name__ == "__main__":
    main()
