"""CropMagnifier — 순수 헬퍼 + 위젯 + CropTool 통합."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage


def _solid(w, h, color="#FFFFFF"):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(color))
    return img


def _canvas(qtbot, w=100, h=80):
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.canvas import LayerCanvas
    stack = LayerStack(QSize(w, h))
    stack.add_layer(ImageLayer(id=1, name="bg", pixmap=_solid(w, h)))
    canvas = LayerCanvas(stack)
    qtbot.addWidget(canvas)
    return canvas


# --- Task 1: 순수 헬퍼 ---

def test_effective_src_size_default():
    from image_editor.tools.crop_magnifier import effective_src_size, SRC_SIZE
    # 큰 이미지: 기본 SRC_SIZE(=15) 그대로
    assert effective_src_size(1000, 800) == SRC_SIZE


def test_effective_src_size_small_image():
    from image_editor.tools.crop_magnifier import effective_src_size
    # 한 변이 SRC_SIZE 보다 작으면 그만큼 줄이고, 최소 1
    assert effective_src_size(10, 200) == 10
    assert effective_src_size(0, 0) == 1


def test_clamp_src_origin_center():
    from image_editor.tools.crop_magnifier import clamp_src_origin
    # 중앙 근처는 center - src//2
    assert clamp_src_origin(50, 40, 15, 100, 80) == (43, 33)


def test_clamp_src_origin_edges():
    from image_editor.tools.crop_magnifier import clamp_src_origin
    # 좌상단 밖으로 못 나감
    assert clamp_src_origin(0, 0, 15, 100, 80) == (0, 0)
    # 우하단: img_w/h - src_size 로 클램프
    assert clamp_src_origin(100, 80, 15, 100, 80) == (85, 65)


def test_loupe_position_default_offset():
    from image_editor.tools.crop_magnifier import loupe_position, _MAG_OFFSET
    # 여유 있는 영역: 커서 우하단으로 offset
    assert loupe_position(10, 10, 500, 500) == (10 + _MAG_OFFSET, 10 + _MAG_OFFSET)


def test_loupe_position_flips_near_edges():
    from image_editor.tools.crop_magnifier import (
        loupe_position, MAG_W, MAG_H, _MAG_OFFSET,
    )
    # 오른쪽/아래 가장자리: 커서 좌상단으로 플립
    x, y = loupe_position(490, 490, 500, 500)
    assert x == 490 - _MAG_OFFSET - MAG_W
    assert y == 490 - _MAG_OFFSET - MAG_H


# --- Task 2: 위젯 ---

def test_magnifier_fixed_size(qtbot):
    from image_editor.tools.crop_magnifier import CropMagnifier, MAG_W, MAG_H
    mag = CropMagnifier()
    qtbot.addWidget(mag)
    assert mag.width() == MAG_W and mag.height() == MAG_H


def test_magnifier_renders_source_color(qtbot):
    from image_editor.tools.crop_magnifier import CropMagnifier
    mag = CropMagnifier()
    qtbot.addWidget(mag)
    mag.set_source(_solid(100, 80, "#0000FF"))  # 순수 파랑
    mag.update_at(QPoint(50, 40), None)
    img = mag.grab().toImage()
    # 렌즈 안(십자선/테두리 피한 지점)은 파란 소스에서 온 색
    c = img.pixelColor(20, 20)
    assert c.blue() > 200 and c.red() < 80


def test_magnifier_transparent_for_mouse(qtbot):
    from image_editor.tools.crop_magnifier import CropMagnifier
    mag = CropMagnifier()
    qtbot.addWidget(mag)
    assert mag.testAttribute(Qt.WA_TransparentForMouseEvents) is True


# --- Task 3: CropTool 수명주기 ---

def test_magnifier_created_on_activate(qtbot):
    from image_editor.tools.crop import CropTool
    from image_editor.tools.crop_magnifier import CropMagnifier
    canvas = _canvas(qtbot)
    tool = CropTool()
    canvas.set_tool(tool)
    assert isinstance(tool._mag, CropMagnifier)
    assert tool._mag.parent() is canvas.viewport()


def test_no_magnifier_without_view(qtbot):
    """뷰가 없는 bare scene(헤드리스): 돋보기 없이도 크롭 동작 정상."""
    from PySide6.QtWidgets import QGraphicsScene
    from image_editor.tools.crop import CropTool
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 100, 80)
    tool = CropTool()
    tool.activated(scene)
    assert tool._mag is None
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(40, 40))
    tool.mouse_release(scene, QPointF(40, 40))
    assert tool.current_rect().width() == 30 and tool.current_rect().height() == 30


def test_magnifier_destroyed_on_deactivate(qtbot):
    from image_editor.tools.crop import CropTool
    canvas = _canvas(qtbot)
    tool = CropTool()
    canvas.set_tool(tool)
    assert tool._mag is not None
    canvas.set_tool(None)   # 크롭 도구 비활성 → deactivated
    assert tool._mag is None


# --- Task 4: 커서 추종 + 크기 라벨 ---

def test_magnifier_follows_cursor_on_hover(qtbot):
    from image_editor.tools.crop import CropTool
    canvas = _canvas(qtbot)
    tool = CropTool()
    canvas.set_tool(tool)
    tool.mouse_move(canvas.scene(), QPointF(30, 25))   # 드래그 아님(hover)
    assert tool._mag._center == QPoint(30, 25)
    assert tool._mag._rect_size is None                # 사각형 없음 → 크기 라벨 "—"
    # show() 가 호출됐는지 확인 — isVisible() 은 부모(캔버스) 미표시 시 False 라
    # isHidden()(명시적 hide 여부, 부모 무관)으로 검증.
    assert tool._mag.isHidden() is False


def test_magnifier_rect_size_during_draw(qtbot):
    from image_editor.tools.crop import CropTool
    canvas = _canvas(qtbot)
    tool = CropTool()
    canvas.set_tool(tool)
    tool.mouse_press(canvas.scene(), QPointF(10, 10))
    tool.mouse_move(canvas.scene(), QPointF(50, 40))   # 드래그로 사각형 그리는 중
    assert tool._mag._center == QPoint(50, 40)
    assert tool._mag._rect_size == QSize(40, 30)
