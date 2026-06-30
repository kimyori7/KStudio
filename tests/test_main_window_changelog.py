import pytest

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.changelog_dialog import ChangelogDialog


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    win = MainWindow(AppSettings(), f)
    qtbot.addWidget(win)
    return win


def test_show_changelog_opens_dialog(w, monkeypatch):
    opened = {}

    def fake_exec(self):
        opened["title"] = self.windowTitle()
        return 0

    monkeypatch.setattr(ChangelogDialog, "exec", fake_exec, raising=True)
    w._show_changelog()
    assert opened.get("title") == "패치 내역"


def test_menu_changelog_signal_wired_to_handler(w, monkeypatch):
    opened = {}

    def fake_exec(self):
        opened["title"] = self.windowTitle()
        return 0

    monkeypatch.setattr(ChangelogDialog, "exec", fake_exec, raising=True)
    w.menu_bar.changelog_action.trigger()   # 메뉴 → changelog_requested → _show_changelog
    assert opened.get("title") == "패치 내역"
