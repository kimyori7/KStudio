"""HotkeyPresetDialog 두 차원 라디오 단위 테스트."""
from __future__ import annotations

import pytest

from screen_recorder.ui.hotkey_preset_dialog import HotkeyPresetDialog


@pytest.fixture
def dialog(qtbot):
    d = HotkeyPresetDialog(current_global="kstudio-default", current_player="kstudio-default")
    qtbot.addWidget(d)
    return d


def test_initial_selection_is_none(dialog):
    assert dialog.selected_global is None
    assert dialog.selected_player is None


def test_default_radios_match_current(dialog):
    """다이얼로그 열릴 때 current_* 인자에 해당하는 라디오가 체크돼야."""
    assert dialog._global_radios["kstudio-default"].isChecked()
    assert dialog._player_radios["kstudio-default"].isChecked()


def test_apply_returns_both_dimensions(dialog, qtbot):
    """다른 옵션 선택 후 적용 버튼 → 두 차원 모두 set."""
    dialog._global_radios["windows-standard"].setChecked(True)
    dialog._player_radios["goom-style"].setChecked(True)
    dialog._on_apply()
    assert dialog.selected_global == "windows-standard"
    assert dialog.selected_player == "goom-style"


def test_skip_keeps_both_none(dialog, qtbot):
    """건너뛰기 = 두 차원 모두 None."""
    dialog._global_radios["windows-standard"].setChecked(True)
    dialog._on_skip()
    assert dialog.selected_global is None
    assert dialog.selected_player is None


def test_can_mix_dimensions(qtbot):
    """차원 1 = 윈도우 표준 + 차원 2 = 곰플 호환 같은 자유 조합 가능."""
    d = HotkeyPresetDialog(current_global="windows-standard", current_player="goom-style")
    qtbot.addWidget(d)
    d._on_apply()
    assert d.selected_global == "windows-standard"
    assert d.selected_player == "goom-style"
