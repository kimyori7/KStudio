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


def test_file_menu_actions_present(qtbot):
    from screen_recorder.ui.menu_bar import build_menu_bar
    from PySide6.QtWidgets import QMainWindow
    win = QMainWindow()
    qtbot.addWidget(win)
    actions = build_menu_bar(win)
    file_action_names = [a.text() for a in actions["file"]]
    assert any("열기" in n for n in file_action_names)
    assert any("저장" in n and "다른" not in n for n in file_action_names)
    assert any("다른 이름으로" in n for n in file_action_names)
    assert any("내보내기" in n for n in file_action_names)


def test_image_menu_has_background_remove(qtbot):
    from screen_recorder.ui.menu_bar import build_menu_bar
    from PySide6.QtWidgets import QMainWindow
    win = QMainWindow()
    qtbot.addWidget(win)
    actions = build_menu_bar(win)
    img_names = [a.text() for a in actions.get("image", [])]
    assert any("배경 제거" in n for n in img_names)
