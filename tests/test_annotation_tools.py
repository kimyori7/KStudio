from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QUndoStack

from image_editor.scene import AnnotationScene
from image_editor.items.rect import RectAnnotationItem
from image_editor.tools.select import SelectTool


def _scene():
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    return AnnotationScene(img)


def test_select_tool_click_empty_clears_selection(qtbot):
    scene = _scene()
    r = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#000"), 2)
    scene.add_annotation(r)
    r.setSelected(True)

    tool = SelectTool()
    tool.mouse_press(scene, QPointF(150, 150))  # 빈 곳
    assert r.isSelected() is False


def test_select_tool_click_on_item_selects_it(qtbot):
    scene = _scene()
    r = RectAnnotationItem(QRectF(10, 10, 50, 50), QColor("#000"), 2)
    scene.add_annotation(r)

    tool = SelectTool()
    tool.mouse_press(scene, QPointF(20, 20))
    assert r.isSelected() is True


from image_editor.tools.rect import RectTool


def test_rect_tool_drag_creates_rect(qtbot):
    scene = _scene()
    stack = QUndoStack()
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2,
                    shift_held=lambda: False, undo_stack=stack)
    tool.mouse_press(scene, QPointF(10, 20))
    tool.mouse_move(scene, QPointF(60, 70))
    tool.mouse_release(scene, QPointF(60, 70))

    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 1
    r = rects[0].rect()
    assert r.x() == 10 and r.y() == 20
    assert r.width() == 50 and r.height() == 50
    assert stack.count() == 1  # AddAnnotationCommand 푸시됨


def test_rect_tool_tiny_drag_is_cancelled(qtbot):
    scene = _scene()
    stack = QUndoStack()
    tool = RectTool(color=QColor("#FF0000"), thickness_step=2,
                    shift_held=lambda: False, undo_stack=stack)
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(13, 12))
    tool.mouse_release(scene, QPointF(13, 12))
    rects = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)]
    assert len(rects) == 0
    assert stack.count() == 0


def test_rect_tool_shift_forces_square(qtbot):
    scene = _scene()
    tool = RectTool(color=QColor("#000"), thickness_step=1,
                    shift_held=lambda: True, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(0, 0))
    tool.mouse_move(scene, QPointF(80, 40))
    tool.mouse_release(scene, QPointF(80, 40))
    r = [a for a in scene.annotations() if isinstance(a, RectAnnotationItem)][0]
    assert r.rect().width() == 40
    assert r.rect().height() == 40


from image_editor.tools.arrow import ArrowTool
from image_editor.items.arrow import ArrowAnnotationItem


def test_arrow_tool_drag_creates_arrow(qtbot):
    scene = _scene()
    tool = ArrowTool(color=QColor("#000"), thickness_step=2,
                     shift_held=lambda: False, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(100, 50))
    tool.mouse_release(scene, QPointF(100, 50))
    arrows = [a for a in scene.annotations() if isinstance(a, ArrowAnnotationItem)]
    assert len(arrows) == 1
    assert arrows[0].start() == QPointF(10, 10)
    assert arrows[0].end() == QPointF(100, 50)


def test_arrow_tool_tiny_drag_cancelled(qtbot):
    scene = _scene()
    tool = ArrowTool(color=QColor("#000"), thickness_step=2,
                     shift_held=lambda: False, undo_stack=QUndoStack())
    tool.mouse_press(scene, QPointF(10, 10))
    tool.mouse_move(scene, QPointF(11, 11))
    tool.mouse_release(scene, QPointF(11, 11))
    assert len([a for a in scene.annotations() if isinstance(a, ArrowAnnotationItem)]) == 0


from PySide6.QtWidgets import QGraphicsScene
from image_editor.tools.text import TextTool
from image_editor.items.text import TextAnnotationItem


def test_text_tool_click_creates_editing_text(qtbot):
    # 편집 중인 텍스트는 live_scene 에 들어가야 키보드 입력이 도달한다 (AnnotationLayer
    # scene 은 헤드리스라 setFocus 해도 키 이벤트가 못 옴).
    scene = _scene()
    live_scene = QGraphicsScene()
    tool = TextTool(color=QColor("#000"), undo_stack=QUndoStack(), live_scene=live_scene)
    tool.mouse_press(scene, QPointF(40, 40))
    tool.mouse_release(scene, QPointF(40, 40))
    # 편집 중에는 live_scene 에 있고 annotation scene 에는 없다.
    assert [a for a in scene.annotations() if isinstance(a, TextAnnotationItem)] == []
    live_texts = [it for it in live_scene.items() if isinstance(it, TextAnnotationItem)]
    assert len(live_texts) == 1
    assert live_texts[0].pos_f() == QPointF(40, 40)


def test_text_tool_empty_text_is_cleaned_on_commit(qtbot):
    scene = _scene()
    live_scene = QGraphicsScene()
    tool = TextTool(color=QColor("#000"), undo_stack=QUndoStack(), live_scene=live_scene)
    tool.mouse_press(scene, QPointF(40, 40))
    tool.mouse_release(scene, QPointF(40, 40))
    tool.commit_active(scene)  # 빈 채로 확정
    assert [a for a in scene.annotations() if isinstance(a, TextAnnotationItem)] == []
    assert [it for it in live_scene.items() if isinstance(it, TextAnnotationItem)] == []


def test_text_tool_committed_text_lands_in_annotation_scene(qtbot):
    # 비어있지 않은 텍스트는 commit 후 AnnotationLayer scene 으로 이동해야 한다.
    scene = _scene()
    live_scene = QGraphicsScene()
    stack = QUndoStack()
    tool = TextTool(color=QColor("#000"), undo_stack=stack, live_scene=live_scene)
    tool.mouse_press(scene, QPointF(50, 60))
    tool.mouse_release(scene, QPointF(50, 60))
    # 입력된 텍스트 흉내 — 편집 중인 아이템에 직접 set_text.
    assert tool._active is not None
    tool._active.set_text("hello")
    tool.commit_active(scene)
    texts = [a for a in scene.annotations() if isinstance(a, TextAnnotationItem)]
    assert len(texts) == 1
    assert texts[0].text() == "hello"
    assert texts[0].pos_f() == QPointF(50, 60)
    assert [it for it in live_scene.items() if isinstance(it, TextAnnotationItem)] == []
    assert stack.count() == 1
