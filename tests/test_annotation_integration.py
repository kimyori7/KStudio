"""사용자 시나리오 통합 — 캡처→그림→저장→재편집→재저장."""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.screenshot_viewer import ScreenshotViewer


def _img(w=200, h=150) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    return img


def test_full_flow_draw_save_edit_resave(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)

    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_img(), source_label="region")

    # 사각형 도구로 전환 + 빨강 선택 + 두께 3
    v.annotation_toolbar.set_current_tool("rect")
    v.annotation_toolbar.set_current_color(QColor("#FF0000"))
    v.annotation_toolbar.set_current_thickness_step(3)

    tab = v.current_tab()
    # 도구 직접 호출로 사각형 그리기
    tool = tab.canvas.current_tool()
    tool.mouse_press(tab.canvas.scene(), QPointF(20, 20))
    tool.mouse_move(tab.canvas.scene(), QPointF(100, 80))
    tool.mouse_release(tab.canvas.scene(), QPointF(100, 80))

    # 저장되지 않은 상태
    assert tab.needs_save() is True
    assert v.tab_title(0).startswith("● ")

    # 저장
    v.save_current_tab()
    assert tab.needs_save() is False
    assert not v.tab_title(0).startswith("● ")
    saved = tab.saved_path()
    assert saved is not None and saved.exists()
    first_mtime = saved.stat().st_mtime_ns

    # 재저장 (변경 없음) — no-op
    v.save_current_tab()
    assert saved.stat().st_mtime_ns == first_mtime

    # 주석 하나 더 추가 → 다시 dirty
    tool = tab.canvas.current_tool()
    tool.mouse_press(tab.canvas.scene(), QPointF(120, 20))
    tool.mouse_move(tab.canvas.scene(), QPointF(180, 80))
    tool.mouse_release(tab.canvas.scene(), QPointF(180, 80))
    assert tab.needs_save() is True

    # 재저장 — 같은 경로 덮어쓰기
    v.save_current_tab()
    assert tab.saved_path() == saved
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1

    # Undo 가능
    assert tab.undo_stack.canUndo() is True
    tab.undo_stack.undo()
    assert tab.needs_save() is True  # 저장 시점과 달라짐
    tab.undo_stack.redo()
    assert tab.needs_save() is False  # 저장 시점과 정확히 일치


def test_color_thickness_persist_across_viewer_restart(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)

    v.annotation_toolbar.set_current_color(QColor("#123456"))
    v.annotation_toolbar.set_current_thickness_step(4)

    # 새 뷰어를 같은 settings 로 열어도 복원됨
    v2 = ScreenshotViewer(settings)
    qtbot.addWidget(v2)
    assert v2.annotation_toolbar.current_color() == QColor("#123456")
    assert v2.annotation_toolbar.current_thickness_step() == 4
