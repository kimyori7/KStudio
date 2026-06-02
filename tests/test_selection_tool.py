"""SelectionTool + SelectionOverlay — 사각형 영역 선택 + marching-ants 시각화."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    return img


def _setup(qtbot):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.selection import SelectionModel
    from image_editor.tools.selection import SelectionTool
    stack = LayerStack(QSize(100, 80))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(100, 80)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    model = SelectionModel()
    canvas.attach_selection(model)
    tool = SelectionTool(model)
    canvas.set_tool(tool)
    return canvas, model, tool


def test_drag_creates_selection(qtbot):
    """드래그 → SelectionModel.rect 가 그 영역으로 설정."""
    canvas, model, tool = _setup(qtbot)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_move(canvas.scene(), QPointF(40, 30))
    tool.mouse_release(canvas.scene(), QPointF(40, 30))
    r = model.rect()
    assert r is not None
    assert r.x() == 10 and r.y() == 10
    assert r.width() == 30 and r.height() == 20


def test_tiny_drag_does_not_create_selection(qtbot):
    """2px 미만 드래그는 selection 으로 인정 안 함 (오클릭 방어)."""
    canvas, model, tool = _setup(qtbot)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_release(canvas.scene(), QPointF(10, 10))
    assert model.has_selection() is False


def test_escape_clears_selection(qtbot):
    canvas, model, tool = _setup(qtbot)
    model.set_rect(QRect(5, 5, 30, 20))
    tool.key_escape(canvas.scene())
    assert model.has_selection() is False


def test_handle_drag_resizes_selection(qtbot):
    """기존 selection 모서리 핸들을 잡아 끌면 해당 모서리만 이동."""
    canvas, model, tool = _setup(qtbot)
    model.set_rect(QRect(20, 20, 30, 30))   # 50, 50 우하단
    # 우하단 모서리(50, 50)를 잡아 +10, +5 이동.
    tool.mouse_press(canvas.scene(), QPointF(50, 50))
    tool.mouse_move(canvas.scene(), QPointF(60, 55))
    tool.mouse_release(canvas.scene(), QPointF(60, 55))
    r = model.rect()
    assert r is not None
    # 좌상단 그대로, 우하단만 이동 — 40×35.
    assert r.x() == 20 and r.y() == 20
    assert r.width() == 40 and r.height() == 35


def test_overlay_creates_items_when_rect_set(qtbot):
    """SelectionOverlay 가 model 의 rect 가 생기는 즉시 scene 에 아이템을 올린다."""
    canvas, model, _tool = _setup(qtbot)
    # 초기엔 비어 있음.
    items_before = [it for it in canvas.scene().items()
                    if it.zValue() >= 99_999]
    assert items_before == []
    model.set_rect(QRect(10, 10, 30, 20))
    items_after = [it for it in canvas.scene().items()
                   if it.zValue() >= 99_999]
    # 흰 실선 + 검정 점선 두 아이템.
    assert len(items_after) == 2


def test_overlay_removes_items_when_cleared(qtbot):
    canvas, model, _tool = _setup(qtbot)
    model.set_rect(QRect(10, 10, 30, 20))
    model.clear()
    items = [it for it in canvas.scene().items() if it.zValue() >= 99_999]
    assert items == []


def _setup_sized(qtbot, cw, ch):
    """주어진 캔버스 크기로 캔버스 + selection 모델을 만든다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.selection import SelectionModel
    stack = LayerStack(QSize(cw, ch))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(cw, ch)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    model = SelectionModel()
    canvas.attach_selection(model)
    return canvas, model, stack


def test_selection_clamped_when_canvas_shrinks(qtbot):
    """캔버스가 줄어들면 기존 selection 도 새 경계 안으로 다시 클램프된다.

    회귀: crop/undo·redo 등으로 canvas_size 가 작아질 때 옛 selection 이
    이미지 밖으로 삐져나가던 버그.
    """
    canvas, model, stack = _setup_sized(qtbot, 200, 140)
    model.set_rect(QRect(20, 20, 160, 100))   # 큰 캔버스 안 — (180,120) 까지
    stack.set_canvas_size(QSize(100, 80))      # 캔버스 축소
    r = model.rect()
    assert r is not None
    # selection 의 우/하단이 새 경계를 넘지 않아야 한다.
    assert r.right() <= 99 and r.bottom() <= 79, f"out of bounds: {r}"
    # 좌상단은 보존, 새 경계와의 교집합으로 클램프.
    assert r.x() == 20 and r.y() == 20
    assert r.width() == 80 and r.height() == 60


def test_selection_cleared_when_canvas_shrinks_past_it(qtbot):
    """축소된 캔버스와 더 이상 겹치지 않는 selection 은 해제된다."""
    canvas, model, stack = _setup_sized(qtbot, 200, 140)
    model.set_rect(QRect(150, 110, 40, 20))   # 우하단 구석
    stack.set_canvas_size(QSize(100, 80))      # 그 영역이 통째로 잘려나감
    assert model.has_selection() is False


def test_selection_clamped_after_crop_command_shrinks_canvas(qtbot):
    """사용자가 보고한 실제 트리거: crop(undo→선택→redo 등)으로 캔버스가
    선택보다 작아지면 선택이 새 경계 안으로 클램프된다.

    crop 도구 시작은 선택을 비우지만, undo 후 다시 선택하고 redo 하면 선택이
    재크롭된 캔버스를 넘어선다 — CropCommand.redo 가 set_canvas_size 를 부르므로
    canvas 의 재클램프가 작동해야 한다.
    """
    from image_editor.operations.crop import CropCommand
    canvas, model, stack = _setup_sized(qtbot, 200, 140)
    model.set_rect(QRect(0, 0, 200, 140))      # 큰 캔버스 전체 선택
    CropCommand(stack, QRect(0, 0, 100, 80)).redo()   # 캔버스 100×80 으로 축소
    r = model.rect()
    assert r is not None
    assert r.right() <= 99 and r.bottom() <= 79, f"crop 후 out of bounds: {r}"
