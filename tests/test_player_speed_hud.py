"""PlayerWidget — show_speed_hud 의 rate_label 포맷.

회귀: 정수 배속 (10×) 에서 rate_label 이 "10" → rstrip("0") → "1" 로 깎여
HUD 에 "1× 배속" 으로 잘못 표시되던 버그.
"""
from __future__ import annotations

import pytest

from screen_recorder.ui.video.player_widget import PlayerWidget


def _show_hud_get_label(qtbot, rate: float) -> str:
    p = PlayerWidget()
    qtbot.addWidget(p)
    p.show_speed_hud(rate)
    text = p._speed_hud.text()
    p.deleteLater()
    return text


def test_speed_hud_label_10x(qtbot):
    """10×: 정수 배속도 정확히 '10' 으로 표시."""
    text = _show_hud_get_label(qtbot, 10.0)
    assert "10×" in text, f"expected '10×' in label, got {text!r}"


def test_speed_hud_label_2x(qtbot):
    text = _show_hud_get_label(qtbot, 2.0)
    assert "2×" in text and "20×" not in text and "0×" not in text


def test_speed_hud_label_1_5x(qtbot):
    """소수 배속: trailing 0 정리 (1.50 → 1.5) 는 유지."""
    text = _show_hud_get_label(qtbot, 1.5)
    assert "1.5×" in text


def test_speed_hud_hidden_at_1x(qtbot):
    """1× 면 HUD 자체를 숨김."""
    p = PlayerWidget()
    qtbot.addWidget(p)
    p.show_speed_hud(1.0)
    assert not p._speed_hud.isVisible()
    p.deleteLater()


def test_speed_hud_label_100x(qtbot):
    """극단값 100× — '1' 로 깎이지 않는지 (rstrip 회귀 보호)."""
    text = _show_hud_get_label(qtbot, 100.0)
    assert "100×" in text
