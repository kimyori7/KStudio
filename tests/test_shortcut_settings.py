"""ShortcutsPanel — 편집기 단축키 + 글로벌 단축키 통합 패널."""
from __future__ import annotations

import pytest


def test_panel_lists_all_editor_shortcuts(qtbot):
    from screen_recorder.core.settings import EditorShortcuts, HotkeySettings
    from screen_recorder.ui.panels.shortcuts_panel import ShortcutsPanel
    panel = ShortcutsPanel(HotkeySettings(), EditorShortcuts())
    qtbot.addWidget(panel)
    keys = panel.captured_settings_keys()
    # 도구
    assert "tool_select" in keys
    assert "tool_crop" in keys
    # 연산
    assert "op_background_removal" in keys
    # 파일
    assert "file_save" in keys
    assert "file_export_png" in keys


def test_change_shortcut_updates_settings(qtbot):
    from screen_recorder.core.settings import EditorShortcuts, HotkeySettings
    from screen_recorder.ui.panels.shortcuts_panel import ShortcutsPanel
    eshort = EditorShortcuts()
    panel = ShortcutsPanel(HotkeySettings(), eshort)
    qtbot.addWidget(panel)
    panel.set_shortcut_for("tool_crop", "K")
    assert eshort.tool_crop == "K"


def test_reset_to_defaults_restores_v(qtbot):
    from screen_recorder.core.settings import EditorShortcuts, HotkeySettings
    from screen_recorder.ui.panels.shortcuts_panel import ShortcutsPanel
    eshort = EditorShortcuts()
    eshort.tool_select = "Z"
    panel = ShortcutsPanel(HotkeySettings(), eshort)
    qtbot.addWidget(panel)
    panel.reset_to_defaults()
    assert eshort.tool_select == "V"


def test_conflict_detected(qtbot):
    from screen_recorder.core.settings import EditorShortcuts, HotkeySettings
    from screen_recorder.ui.panels.shortcuts_panel import ShortcutsPanel
    eshort = EditorShortcuts()
    panel = ShortcutsPanel(HotkeySettings(), eshort)
    qtbot.addWidget(panel)
    conflict = panel.check_conflict("tool_crop", "V")  # V 는 select
    assert conflict == "tool_select"
