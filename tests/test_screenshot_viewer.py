from pathlib import Path
from PySide6.QtGui import QImage, QColor

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.screenshot_viewer import ScreenshotViewer


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
