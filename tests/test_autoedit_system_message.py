"""MainWindow.append_autoedit_system_message — 채팅 패널에 시스템 메시지 출력."""
from unittest.mock import MagicMock
from screen_recorder.ui.main_window import MainWindow


def test_append_autoedit_system_message_calls_chat_panel(qtbot, tmp_path):
    """MainWindow 가 시스템 메시지를 채팅 패널에 위임."""
    from screen_recorder.core.settings import AppSettings
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    settings = AppSettings()
    win = MainWindow(settings, f)
    qtbot.addWidget(win)
    # chat_panel 의 append_message 호출 검증.
    win.agent_chat_panel.append_message = MagicMock()
    win.append_autoedit_system_message(5, [])
    args, _ = win.agent_chat_panel.append_message.call_args
    msg = args[0]
    assert "5개 효과" in msg.text
    assert "Ctrl+Z" in msg.text


def test_append_autoedit_system_message_lists_failed(qtbot, tmp_path):
    from screen_recorder.core.settings import AppSettings
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    settings = AppSettings()
    win = MainWindow(settings, f)
    qtbot.addWidget(win)
    win.agent_chat_panel.append_message = MagicMock()
    win.append_autoedit_system_message(10, ["bpm", "scene"])
    args, _ = win.agent_chat_panel.append_message.call_args
    msg = args[0]
    assert "bpm" in msg.text
    assert "scene" in msg.text
