from PySide6.QtWidgets import QMainWindow

from screen_recorder.ui.menu_bar import KStudioMenuBar, build_menu_bar


def test_menu_has_youtube_signals(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    assert hasattr(mb, "youtube_video_requested")
    assert hasattr(mb, "youtube_mp3_requested")
    assert mb.youtube_video_action.text() == "유튜브 영상 추출"
    assert mb.youtube_mp3_action.text() == "유튜브 mp3 변환"


def test_youtube_actions_emit(qtbot):
    mb = KStudioMenuBar()
    qtbot.addWidget(mb)
    with qtbot.waitSignal(mb.youtube_video_requested, timeout=1000):
        mb.youtube_video_action.trigger()
    with qtbot.waitSignal(mb.youtube_mp3_requested, timeout=1000):
        mb.youtube_mp3_action.trigger()


def test_build_menu_bar_extra_group(qtbot):
    win = QMainWindow()
    qtbot.addWidget(win)
    groups = build_menu_bar(win)
    assert "extra" in groups
    assert win.menu_bar.youtube_video_action in groups["extra"]
    assert win.menu_bar.youtube_mp3_action in groups["extra"]
