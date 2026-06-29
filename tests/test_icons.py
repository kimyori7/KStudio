"""SVG 아이콘 시스템 단위 테스트."""
from __future__ import annotations
import pytest

from PySide6.QtGui import QImage

from screen_recorder.ui import icons


def test_load_icon_returns_qicon_for_known_name(qtbot):
    icon = icons.load_icon("scissors", size=20)
    assert not icon.isNull()


def test_load_icon_unknown_returns_empty(qtbot):
    icon = icons.load_icon("nonexistent-icon-xyz")
    assert icon.isNull()


def test_known_icons_have_paths():
    """핵심 아이콘 모두 등록돼 있어야 함."""
    for name in ["play", "pause", "volume-2", "volume-x", "scissors", "x",
                  "crop", "chevron-left", "chevron-right", "camera", "maximize",
                  "square-arrow-left", "square-arrow-right", "settings",
                  "mouse-pointer", "square", "type"]:
        assert icons.has_icon(name), f"missing icon: {name}"


def test_icon_render_pixmap_is_correct_size(qtbot):
    pm = icons._render_pixmap("play", 24, icons.COLOR_BASE)
    assert pm.width() == 24
    assert pm.height() == 24


def test_load_icon_caches_same_call(qtbot):
    """같은 이름·size·color 는 같은 pixmap 인스턴스 (LRU 캐시)."""
    pm1 = icons._render_pixmap("scissors", 20, icons.COLOR_BASE)
    pm2 = icons._render_pixmap("scissors", 20, icons.COLOR_BASE)
    assert pm1 is pm2


def test_stop_icon_registered(qtbot):
    assert icons.has_icon("stop")
    assert not icons.load_icon("stop").isNull()


def _avg_color(pm):
    """pixmap 의 불투명 픽셀 평균 RGB."""
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    r = g = b = n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 10:
                r += c.red(); g += c.green(); b += c.blue(); n += 1
    return (r // n, g // n, b // n) if n else (0, 0, 0)


def test_stop_fill_tracks_color_not_black(qtbot):
    """fill='currentColor' 가 _wrap 의 color 토큰을 따라가야 한다(검정 폴백 아님).

    base 색으로 그리면 밝게(>180), disabled 색으로 그리면 어둡게(<140) 채워져야
    채움+disabled 회색이 모두 동작함을 보장.
    """
    rb, gb, bb = _avg_color(icons._render_pixmap("stop", 24, icons.COLOR_BASE))
    assert min(rb, gb, bb) > 180, f"stop base fill 이 검정에 가까움: {(rb, gb, bb)}"
    rd, gd, bd = _avg_color(icons._render_pixmap("stop", 24, icons.COLOR_DISABLED))
    assert max(rd, gd, bd) < 140, f"stop disabled fill 이 회색으로 안 떨어짐: {(rd, gd, bd)}"
