from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.preferences_dialog import PreferencesDialog


def test_dialog_has_five_categories(qtbot):
    s = AppSettings()
    d = PreferencesDialog(s)
    qtbot.addWidget(d)
    assert d.category_list.count() == 5
    titles = [d.category_list.item(i).text() for i in range(5)]
    assert "저장 / 파일명" in titles
    assert "영상·GIF·사운드" in titles
    assert "영상 플레이어" in titles
    assert "단축키" in titles
    assert "일반" in titles


def test_selecting_category_changes_stack(qtbot):
    s = AppSettings()
    d = PreferencesDialog(s)
    qtbot.addWidget(d)
    d.category_list.setCurrentRow(2)
    assert d.stack.currentIndex() == 2


def test_player_panel_edits_propagate(qtbot):
    s = AppSettings()
    d = PreferencesDialog(s)
    qtbot.addWidget(d)
    d.player_panel.skip_spin.setValue(5)
    assert s.player.skip_seconds == 5
