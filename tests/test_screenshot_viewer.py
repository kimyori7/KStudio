from pathlib import Path
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QColor

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.screenshot_viewer import ScreenshotViewer
from screen_recorder.ui.annotation.items.rect import RectAnnotationItem
from screen_recorder.ui.annotation.commands import AddAnnotationCommand


def _make_image(w=10, h=10, color=QColor(255, 0, 0)) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(color)
    return img


def test_viewer_starts_with_no_tabs(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    assert v.tab_count() == 0


def test_add_tab_increments_tab_count_and_focuses_new_tab(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.add_tab(_make_image(color=QColor(0, 255, 0)), source_label="fullscreen")
    assert v.tab_count() == 2
    assert v.current_index() == 1


def test_unsaved_tab_title_has_dot_prefix(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    assert v.tab_title(0).startswith("● ")


def test_saving_tab_removes_dot_prefix(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)  # 대화상자 우회
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.save_current_tab()
    assert not v.tab_title(0).startswith("● ")


def test_save_current_tab_writes_png_to_save_dir(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.save_current_tab()
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1


def test_close_last_tab_closes_window(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    img = _make_image()
    v.add_tab(img, source_label="region")
    # 탭을 저장된 상태로 만들면 close 시 다이얼로그 안 뜸
    tab = v.current_tab()
    tab.mark_saved(Path("/fake.png"))
    v.close_tab(0)
    assert v.tab_count() == 0
    # 창 닫힘은 이벤트 루프가 필요하므로 수동 검증 (Task 15)


def test_viewer_has_annotation_toolbar(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    assert v.annotation_toolbar is not None
    assert v.annotation_toolbar.current_tool_id() == "select"


def test_resave_overwrites_same_path(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.save_current_tab()
    first_path = v.current_tab().saved_path()
    # 주석 하나 추가해서 dirty
    tab = v.current_tab()
    item = RectAnnotationItem(QRectF(0, 0, 5, 5), QColor("#000"), 2)
    tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))
    v.save_current_tab()
    pngs = list(tmp_path.glob("*.png"))
    assert len(pngs) == 1  # 덮어쓰기 (새 파일 생성 안 함)
    assert v.current_tab().saved_path() == first_path


def test_resave_noop_when_clean_and_saved(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.save_current_tab()
    first_mtime = v.current_tab().saved_path().stat().st_mtime_ns
    # 변경 없이 재저장 시도
    v.save_current_tab()
    second_mtime = v.current_tab().saved_path().stat().st_mtime_ns
    assert first_mtime == second_mtime  # 파일 재기록 안 됨


def test_tab_title_has_dot_after_edit(qtbot, tmp_path):
    settings = AppSettings()
    settings.screenshot.save_dir = str(tmp_path)
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.add_tab(_make_image(), source_label="region")
    v.save_current_tab()
    assert not v.tab_title(0).startswith("● ")
    tab = v.current_tab()
    item = RectAnnotationItem(QRectF(0, 0, 5, 5), QColor("#000"), 2)
    tab.undo_stack.push(AddAnnotationCommand(tab.canvas.scene(), item))
    assert v.tab_title(0).startswith("● ")


def test_color_change_persists_to_settings(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.annotation_toolbar.set_current_color(QColor("#123456"))
    assert settings.annotation.last_color == "#123456"


def test_thickness_change_persists_to_settings(qtbot):
    settings = AppSettings()
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    v.annotation_toolbar.set_current_thickness_step(4)
    assert settings.annotation.last_thickness == 4


def test_viewer_inits_toolbar_from_settings(qtbot):
    settings = AppSettings()
    settings.annotation.last_color = "#00FF00"
    settings.annotation.last_thickness = 3
    v = ScreenshotViewer(settings)
    qtbot.addWidget(v)
    assert v.annotation_toolbar.current_color() == QColor("#00FF00")
    assert v.annotation_toolbar.current_thickness_step() == 3
