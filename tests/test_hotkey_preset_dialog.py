"""HotkeyPresetDialog 단위 테스트."""
from __future__ import annotations

import pytest

from screen_recorder.ui.hotkey_preset_dialog import HotkeyPresetDialog


@pytest.fixture
def dialog(qtbot):
    d = HotkeyPresetDialog()
    qtbot.addWidget(d)
    return d


def test_initial_selection_is_none(dialog):
    assert dialog.selected_preset is None


def test_card_click_sets_preset_and_accepts(dialog, qtbot):
    """첫 카드(windows-standard) 클릭 → selected_preset 설정 + accept."""
    # 다이얼로그 안의 첫 _PresetCard 를 찾아 emit
    from screen_recorder.ui.hotkey_preset_dialog import _PresetCard
    cards = dialog.findChildren(_PresetCard)
    assert len(cards) == 2
    # ID 매핑 확인
    presets = sorted([c._preset_id for c in cards])
    assert presets == ["goom-pot", "windows-standard"]
    # 시뮬레이트 클릭
    cards[0].clicked.emit(cards[0]._preset_id)
    assert dialog.selected_preset in ("windows-standard", "goom-pot")


def test_skip_keeps_preset_none(dialog, qtbot):
    """건너뛰기 = selected_preset 그대로 None + accept."""
    from PySide6.QtWidgets import QPushButton
    skip_buttons = [b for b in dialog.findChildren(QPushButton) if "건너뛰기" in b.text()]
    assert len(skip_buttons) == 1
    skip_buttons[0].click()
    assert dialog.selected_preset is None
