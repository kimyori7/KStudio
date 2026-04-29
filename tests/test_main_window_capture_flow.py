from pathlib import Path
import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(20, 20, QImage.Format_ARGB32)
    img.fill(0xFFAA1122)
    return img


@pytest.fixture
def gif_file(tmp_path):
    """Pillow-generated valid 2-frame GIF."""
    from PIL import Image
    p = tmp_path / "out.gif"
    f1 = Image.new("P", (8, 8), 0)
    f2 = Image.new("P", (8, 8), 1)
    palette = [255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6)
    f1.putpalette(palette)
    f2.putpalette(palette)
    f1.save(p, format="GIF", save_all=True, append_images=[f2], duration=100, loop=0)
    return p


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    # 라이브러리 시작 시 디스크 스캔이 사용자 실제 저장 폴더를 읽지 않도록 tmp_path 격리.
    s.screenshot.save_dir = str(tmp_path / "shots")
    s.general.output_dir = str(tmp_path / "videos")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_screenshot_creates_tab_and_library_entry(w):
    w._on_screenshot_captured(_img(), "region")
    assert w.tab_area.count_visible() == 1
    assert len(w.library_model.entries()) == 1


def test_recording_finished_creates_video_tab(w, gif_file):
    w._on_finished(str(gif_file))
    assert w.tab_area.count_visible() == 1
    assert len(w.library_model.entries()) == 1
    assert w.library_model.entries()[0].kind.value == "video"


def test_library_click_opens_existing_tab(w):
    w._on_screenshot_captured(_img(), "region")
    e = w.library_model.entries()[0]
    w._on_screenshot_captured(_img(), "full")
    assert w.tab_area.current_entry_id() != e.id
    w._open_entry(e.id)
    assert w.tab_area.current_entry_id() == e.id


def test_screenshot_does_not_auto_create_annotation_layer(w):
    """캡처 직후엔 select 도구로 리셋되지만, AnnotationLayer 가 자동 생성되면 안 된다.

    select 는 기존 아이템을 조작하는 도구라 레이어가 없으면 빈 동작이면 충분.
    rect/arrow/text 처음 누를 때만 주석 레이어가 자동 생성되어야 한다.
    """
    from image_editor.layers.annotation_layer import AnnotationLayer
    w._on_screenshot_captured(_img(), "region")
    tab = w._current_screenshot_tab()
    assert tab is not None
    has_ann = any(isinstance(l, AnnotationLayer) for l in tab.stack.layers)
    assert has_ann is False, "캡처 직후 AnnotationLayer 가 자동 생성되면 안 됨"
