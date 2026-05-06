from pathlib import Path
import pytest
from PySide6.QtGui import QImage, QColor

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_tool_change_propagates_to_active_canvas(w):
    w._on_screenshot_captured(_img(), "region")
    w._on_tool_changed("rect")
    tab = w.tab_area.currentWidget()
    assert tab.canvas.current_tool().name == "rect"


def test_color_change_propagates(w):
    w._on_screenshot_captured(_img(), "region")
    w._on_color_changed(QColor("#00FF00"))
    assert w.app_settings.annotation.last_color.upper() == "#00FF00"


def test_save_creates_file(w, tmp_path):
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    files = list(tmp_path.glob("*.png"))
    assert len(files) == 1


def test_copy_to_clipboard(w, qtbot):
    from PySide6.QtWidgets import QApplication
    w._on_screenshot_captured(_img(), "region")
    w._copy_current_screenshot()
    cb = QApplication.clipboard()
    assert not cb.image().isNull()


def test_copy_to_clipboard_includes_named_file_url(w, qtbot):
    """클립보드에 이미지뿐 아니라 정식 이름의 임시 파일 URL 도 들어가야
    Slack/탐색기 등이 'image.png' 가 아닌 정식 이름으로 받는다."""
    from PySide6.QtWidgets import QApplication
    w._on_screenshot_captured(_img(), "region")
    w._copy_current_screenshot()
    cb = QApplication.clipboard()
    mime = cb.mimeData()
    urls = mime.urls()
    assert len(urls) == 1, "URL 이 한 개 이상 클립보드에 있어야 한다"
    name = Path(urls[0].toLocalFile()).name
    assert name.lower().endswith(".png")
    # Qt 의 기본 'image.png' 가 아니라 사용자 패턴(screenshot_*) 으로 시작해야.
    assert name != "image.png"
    assert name.startswith("screenshot_") or name.startswith("rec_")


def test_copy_to_clipboard_uses_existing_display_name(w, qtbot, tmp_path):
    """디스크 파일이 있는 탭은 그 파일명을 클립보드에도 그대로 쓴다."""
    from PySide6.QtWidgets import QApplication
    # 먼저 캡처해 저장
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    saved = list(tmp_path.glob("*.png"))[0]
    w._copy_current_screenshot()
    cb = QApplication.clipboard()
    urls = cb.mimeData().urls()
    assert urls
    assert Path(urls[0].toLocalFile()).name == saved.name


def test_cut_to_clipboard_includes_named_file_url(w, qtbot):
    """Ctrl+X 도 같은 클립보드 이름 규칙."""
    from PySide6.QtWidgets import QApplication
    w._on_screenshot_captured(_img(), "region")
    w._cut_current_selection()
    cb = QApplication.clipboard()
    urls = cb.mimeData().urls()
    assert urls
    name = Path(urls[0].toLocalFile()).name
    assert name != "image.png"
    assert name.lower().endswith(".png")
