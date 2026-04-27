from screen_recorder.ui.menu_bar import KStudioMenuBar


def test_menus_exist(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    titles = [a.text() for a in mb.actions()]
    assert "파일" in titles
    assert "편집" in titles
    assert "보기" in titles
    assert "녹화" in titles
    assert "도움말" in titles


def test_save_action_signal(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    with qtbot.waitSignal(mb.save_requested, timeout=200):
        mb.save_action.trigger()


def test_preferences_action_signal(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    with qtbot.waitSignal(mb.preferences_requested, timeout=200):
        mb.preferences_action.trigger()


def test_undo_redo_signals(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    with qtbot.waitSignal(mb.undo_requested, timeout=200):
        mb.undo_action.trigger()
    with qtbot.waitSignal(mb.redo_requested, timeout=200):
        mb.redo_action.trigger()
