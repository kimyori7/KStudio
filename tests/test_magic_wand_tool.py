"""MagicWandTool — 클릭으로 미리보기, Enter/Delete 로 확정하는 두 단계 동작."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, c=0xFFFFFFFF):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


def _two_color(w, h):
    """좌측 절반 빨강 / 우측 절반 초록 — 서로 색이 멀어 각각 독립 영역."""
    from PySide6.QtGui import qRgba
    img = QImage(w, h, QImage.Format_ARGB32)
    half = w // 2
    for x in range(w):
        c = qRgba(230, 30, 30, 255) if x < half else qRgba(30, 200, 30, 255)
        for y in range(h):
            img.setPixel(x, y, c)
    return img


def _highlight_count(qimg: QImage, x0: int, x1: int) -> int:
    """[x0, x1) 열 범위에서 미리보기 하이라이트(alpha>0) 픽셀 수."""
    n = 0
    for x in range(x0, x1):
        for y in range(qimg.height()):
            if (qimg.pixel(x, y) >> 24) & 0xFF:
                n += 1
    return n


def test_preview_after_commit_shows_only_new_region(qtbot):
    """이미 지운(=commit 된) 영역은 새 영역 선택 미리보기에 다시 표시되면 안 된다.

    회귀 (사용자 보고 2026-06-01): 마술봉 클릭→영역 선택→지우기→다른 영역 선택 시
    '기존에 지웠던 영역도 함께' 빨간 미리보기로 표시됨. 마스크는 누적이 맞지만
    미리보기 오버레이는 이번 클릭으로 새로 선택된 픽셀(delta)만 보여야 한다.
    """
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    W, H = 40, 20
    stack = LayerStack(QSize(W, H))
    layer = ImageLayer(id=1, name="bg", pixmap=_two_color(W, H))
    stack.add_layer(layer)
    stack.set_active_layer(layer.id)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=20)
    canvas.set_tool(tool)

    # 1) 빨강(좌측) 클릭 → commit 모사 (MagicWandApplyCommand 가 하는 일).
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    assert tool.has_pending()
    layer.mask = tool._pending_new_mask   # commit: 빨강 영역 마스크 적용

    # 2) 초록(우측) 클릭 → 미리보기 오버레이 갱신.
    tool.mouse_press(canvas.scene(), QPointF(30, 10))
    assert tool._overlay_item is not None
    preview = tool._overlay_item.pixmap().toImage()

    red_hl = _highlight_count(preview, 0, W // 2)
    green_hl = _highlight_count(preview, W // 2, W)
    assert green_hl > 0, "새로 선택한 초록 영역은 미리보기에 표시돼야 한다."
    assert red_hl == 0, (
        f"이미 지운 빨강 영역이 미리보기에 다시 표시됨 (하이라이트 {red_hl}px)."
    )


def test_click_creates_pending_preview_without_modifying_mask(qtbot):
    """클릭만 하면 마스크는 그대로 — 미리보기 상태로만 들어가야 한다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)

    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    assert layer.mask is None
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    # 마스크는 아직 바뀌면 안 된다.
    assert layer.mask is None
    # 그러나 보류 상태로 들어가 있어야 한다.
    assert tool.has_pending() is True


def test_enter_commits_pending_preview(qtbot):
    """Enter 누르면 commit_requested 시그널이 발화되고 보류가 해제된다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(20, 20))
    stack.add_layer(layer)
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    assert tool.has_pending()
    with qtbot.waitSignal(tool.commit_requested, timeout=500) as blocker:
        tool.key_enter(canvas.scene())
    layer_id, mask, affected = blocker.args
    assert layer_id == 1
    assert isinstance(mask, QImage)
    assert affected is not None
    assert tool.has_pending() is False


def test_delete_also_commits_pending(qtbot):
    """Delete 키도 보류 미리보기를 확정해야 한다 (사용자 직관)."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    # 보류 상태에서 Delete 키 → consumed=True 반환.
    consumed = tool.key_delete(canvas.scene())
    assert consumed is True
    assert tool.has_pending() is False


def test_flood_confined_to_canvas_bounds_after_crop():
    """크롭 후 마술봉 flood-fill 은 캔버스(잘린 후) 영역 밖으로 번지면 안 된다.

    회귀 (사용자 보고 2026-06-02): 자동 크롭은 lazy — pixmap 은 원본 크기를 유지하고
    offset/canvas_size 만 바뀐다. 균일한 색을 마술봉으로 찍으면 connected-component
    가 잘려나간 테두리(off-canvas 픽셀)까지 번져, 미리보기/marching-ants 가 크롭 전
    바깥 영역을 함께 선택한다. bounds(=layer-local 캔버스 창)를 주면 그 안으로 제한돼야 한다.
    """
    from image_editor.operations.magic_wand import compute_magic_wand_mask_with_rect

    # 40x20 전부 흰색. "크롭"으로 좌우 10px 씩 잘려 캔버스는 x=[10,30) 만 보인다고 가정.
    W, H = 40, 20
    pix = _solid(W, H)
    bounds = QRect(10, 0, 20, H)   # layer-local 캔버스 창 = QRect(-offset, canvas_size)

    new_mask, affected = compute_magic_wand_mask_with_rect(
        pix, None, 15, 10, tolerance=10, bounds=bounds,
    )

    assert affected is not None
    # affected bounding rect 은 bounds 안에 완전히 들어가야 한다 (밖으로 안 번짐).
    assert bounds.contains(affected), (
        f"flood 가 캔버스 밖으로 번짐: affected={affected}, bounds={bounds}"
    )
    # 마스크에서 0(=선택) 인 픽셀이 bounds 밖에 하나도 없어야 한다.
    gray = new_mask.convertToFormat(QImage.Format_Grayscale8)
    for x in range(W):
        for y in range(H):
            selected = (gray.pixelColor(x, y).value() == 0)
            inside = bounds.contains(x, y)
            if selected:
                assert inside, f"({x},{y}) 가 캔버스 밖인데 선택됨"


def test_magic_wand_preview_stays_within_canvas_after_crop(qtbot):
    """크롭(offset 음수 + canvas 축소) 후 마술봉 클릭 → 미리보기 오버레이/affected 가
    캔버스 안에 머물러야 한다. (사용자 보고: 모서리에 닿으면 선택 위치가 옮겨짐.)"""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    # 원본 40x20, 전부 흰색. 좌우 10px 잘라낸 크롭을 모사: offset=(-10,0), canvas=20x20.
    W, H = 40, 20
    stack = LayerStack(QSize(W, H))
    layer = ImageLayer(id=1, name="bg", pixmap=_solid(W, H))
    stack.add_layer(layer)
    stack.set_active_layer(layer.id)
    layer.offset = QPoint(-10, 0)
    stack.set_canvas_size(QSize(20, H))

    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)

    captured = []
    tool.preview_changed.connect(lambda lid, aff: captured.append(aff))

    # 캔버스 중앙(scene x=10) 클릭 → layer-local x=20.
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    assert tool.has_pending()

    # affected (layer-local) 를 scene 으로 옮긴 marching-ants rect 이 캔버스 안에 있어야 한다.
    affected = captured[-1]
    assert affected is not None
    scene_rect = QRect(affected).translated(layer.offset.x(), layer.offset.y())
    canvas_rect = QRect(0, 0, 20, H)
    assert canvas_rect.contains(scene_rect), (
        f"마술봉 선택이 캔버스 밖으로 나감: scene_rect={scene_rect}, canvas={canvas_rect}"
    )


def test_escape_clears_pending_without_commit(qtbot):
    """Esc 는 보류 미리보기만 폐기 — commit 시그널은 발화되지 않는다."""
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    from image_editor.tools.magic_wand import MagicWandTool

    stack = LayerStack(QSize(20, 20))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(20, 20)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    tool = MagicWandTool(stack, tolerance=10)
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(5, 5))
    assert tool.has_pending()
    with qtbot.assertNotEmitted(tool.commit_requested):
        with qtbot.waitSignal(tool.cancelled, timeout=500):
            tool.key_escape(canvas.scene())
    assert tool.has_pending() is False
