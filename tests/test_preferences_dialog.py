from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.preferences_dialog import PreferencesDialog


def test_dialog_has_categories(qtbot):
    s = AppSettings()
    d = PreferencesDialog(s)
    qtbot.addWidget(d)
    assert d.category_list.count() >= 5
    titles = [d.category_list.item(i).text() for i in range(d.category_list.count())]
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


def test_audio_export_dir_persists(qtbot):
    """저장/파일명 패널의 🎵 오디오 저장 폴더 → preferences.audio_export_dir 영속."""
    s = AppSettings()
    d = PreferencesDialog(s)
    qtbot.addWidget(d)
    d.screenshot_panel.aud_dir_edit.setText(r"D:\MyAudio")
    d.screenshot_panel._sync()
    assert s.preferences.audio_export_dir == r"D:\MyAudio"


def test_audio_export_dir_round_trips_through_json(tmp_path):
    """audio_export_dir 가 settings.json 저장→로드로 보존된다."""
    from screen_recorder.core import settings as st
    s = AppSettings()
    s.preferences.audio_export_dir = r"E:\Voices"
    p = tmp_path / "settings.json"
    st.save(s, p)
    assert st.load(p).preferences.audio_export_dir == r"E:\Voices"
