"""SVG 아이콘 시스템 단위 테스트."""
from __future__ import annotations
import pytest

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
