"""녹화 중 미니 컨트롤(우하단 3버튼) 단위 테스트.

옛 유니코드 글리프(⏸ ⏹ ✕) → SVG 아이콘 전환 회귀 보호.
"""
from __future__ import annotations

from screen_recorder.ui.overlay.mini_control import MiniControl


def test_buttons_use_icons_not_glyph_text(qtbot):
    """세 버튼 모두 텍스트 없이 SVG 아이콘을 가져야 한다(폰트 폴백 깨짐 방지)."""
    mc = MiniControl()
    qtbot.addWidget(mc)
    for btn in (mc.pause_btn, mc.stop_btn, mc.close_btn):
        assert btn.text() == "", f"버튼에 글리프 텍스트가 남아있음: {btn.text()!r}"
        assert not btn.icon().isNull(), "버튼 아이콘이 비어있음"


def test_set_paused_toggles_pause_icon(qtbot):
    """set_paused 가 일시정지↔재개 아이콘/툴팁을 토글한다."""
    mc = MiniControl()
    qtbot.addWidget(mc)

    mc.set_paused(True)
    paused_key = mc.pause_btn.icon().cacheKey()
    assert mc.pause_btn.toolTip() == "재개"

    mc.set_paused(False)
    running_key = mc.pause_btn.icon().cacheKey()
    assert mc.pause_btn.toolTip() == "일시정지"

    assert paused_key != running_key, "play/pause 아이콘이 실제로 바뀌지 않음"
