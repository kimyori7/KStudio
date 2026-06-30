from PySide6.QtWidgets import QMainWindow
from screen_recorder.ui.menu_bar import build_menu_bar


def test_changelog_action_in_help(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)
    groups = build_menu_bar(win)
    assert win.menu_bar.changelog_action in groups["help"]
    assert win.menu_bar.changelog_action.text() == "패치 내역"


def test_changelog_action_emits_signal(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)
    build_menu_bar(win)
    with qtbot.waitSignal(win.menu_bar.changelog_requested, timeout=500):
        win.menu_bar.changelog_action.trigger()
