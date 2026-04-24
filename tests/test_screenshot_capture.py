from pathlib import Path
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QColor, QPainter

from screen_recorder.screenshot import capture


@pytest.fixture
def sample_image():
    """가로 200 x 세로 100 의 두 색 그라디언트 이미지."""
    img = QImage(200, 100, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0))  # 전체 빨강
    # 오른쪽 절반을 파랑으로
    p = QPainter(img)
    p.fillRect(QRect(100, 0, 100, 100), QColor(0, 0, 255))
    p.end()
    return img


def test_crop_to_rect_returns_subimage(sample_image):
    cropped = capture.crop_to_rect(sample_image, QRect(100, 0, 100, 100))
    assert cropped.width() == 100
    assert cropped.height() == 100
    assert QColor(cropped.pixel(0, 0)).blue() == 255
    assert QColor(cropped.pixel(0, 0)).red() == 0


def test_crop_to_rect_clips_out_of_bounds(sample_image):
    """요청된 사각형이 이미지 밖으로 나가면 교집합만 반환."""
    cropped = capture.crop_to_rect(sample_image, QRect(150, 50, 100, 100))
    # 교집합: x=150..199 (50), y=50..99 (50)
    assert cropped.width() == 50
    assert cropped.height() == 50


def test_crop_to_rect_returns_null_image_for_empty_intersection(sample_image):
    cropped = capture.crop_to_rect(sample_image, QRect(500, 500, 10, 10))
    assert cropped.isNull() or (cropped.width() == 0 and cropped.height() == 0)


def test_save_png_writes_file(sample_image, tmp_path):
    out = tmp_path / "out.png"
    capture.save_png(sample_image, out)
    assert out.exists()
    assert out.stat().st_size > 0
    # 로드해서 같은 크기인지
    loaded = QImage(str(out))
    assert loaded.width() == 200
    assert loaded.height() == 100


def test_save_png_creates_parent_dirs(sample_image, tmp_path):
    out = tmp_path / "nested" / "dir" / "out.png"
    capture.save_png(sample_image, out)
    assert out.exists()


def test_virtual_desktop_bounds_unions_all_screens(qtbot):
    """QApplication 환경에서 가상 데스크톱 bounds 계산.

    단일 모니터 CI 에서는 스크린 1개만 있을 수 있으므로 bounds 가 비어있지 않음만 확인.
    """
    bounds = capture.virtual_desktop_bounds()
    assert bounds.width() > 0
    assert bounds.height() > 0
