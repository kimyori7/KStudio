from screen_recorder.core.settings import PlayerSettings
from screen_recorder.ui.panels.player_panel import PlayerPanel


def test_loads_initial_values(qtbot):
    s = PlayerSettings(skip_seconds=2, skip_medium_seconds=8, skip_large_seconds=20)
    p = PlayerPanel(s)
    qtbot.addWidget(p)
    assert p.skip_spin.value() == 2
    assert p.medium_spin.value() == 8
    assert p.large_spin.value() == 20


def test_changing_spin_updates_settings(qtbot):
    s = PlayerSettings()
    p = PlayerPanel(s)
    qtbot.addWidget(p)
    p.skip_spin.setValue(3)
    assert s.skip_seconds == 3


def test_emits_settings_changed_on_edit(qtbot):
    s = PlayerSettings()
    p = PlayerPanel(s)
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.settings_changed, timeout=200):
        p.medium_spin.setValue(7)
