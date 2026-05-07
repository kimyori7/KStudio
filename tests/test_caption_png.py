"""caption_png — 영상 해상도 투명 PNG 렌더."""
import tempfile
from pathlib import Path

import pytest

from screen_recorder.effects.types.caption import (
    CaptionEffect, Fade, Position,
)
from screen_recorder.encode.caption_png import render_caption_png


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_render_creates_png_at_video_resolution(qtbot, tmp_dir):
    c = CaptionEffect(in_ms=0, out_ms=2000, text="hello",
                      position=Position(anchor="bottom-center"))
    out = tmp_dir / "cap.png"
    render_caption_png(c, surface_w=1920, surface_h=1080, dst=out, sample_ms=1000)
    assert out.exists()
    from PySide6.QtGui import QImage
    img = QImage(str(out))
    assert img.width() == 1920
    assert img.height() == 1080
    assert img.hasAlphaChannel()


def test_render_outside_window_creates_transparent_png(qtbot, tmp_dir):
    """sample_ms 가 in_ms~out_ms 밖이면 빈 (완전 투명) PNG."""
    c = CaptionEffect(in_ms=0, out_ms=1000, text="x")
    out = tmp_dir / "empty.png"
    render_caption_png(c, surface_w=100, surface_h=100, dst=out, sample_ms=5000)
    from PySide6.QtGui import QImage
    img = QImage(str(out))
    # 첫 픽셀의 알파가 0 인지 (완전 투명).
    assert img.pixelColor(50, 50).alpha() == 0
