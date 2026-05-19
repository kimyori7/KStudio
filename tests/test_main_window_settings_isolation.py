"""MainWindow 가 __init__ 중에 사용자 실제 settings.json 을 건드리지 않는지 회귀 테스트.

배경: Qt 의 setCurrentIndex / setChecked 같은 프로그램 호출이 일부 시그널을 발화시켜
핸들러(_on_fullscreen_monitor_changed 등) 가 _persist_settings 를 호출하면, 테스트가
일회용으로 잡아 둔 save_dir(예: pytest tmp) 가 사용자 실제 settings.json 에
영구 기록돼 다음 실행에 잘못된 폴더를 쓰게 된다."""
from __future__ import annotations
from pathlib import Path
import pytest

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings
from screen_recorder.core import settings as settings_module


def test_constructing_main_window_does_not_write_settings_file(qtbot, tmp_path, monkeypatch):
    fake_settings_dir = tmp_path / "appdata"
    fake_settings_path = fake_settings_dir / "settings.json"
    monkeypatch.setattr(settings_module, "settings_path", lambda: fake_settings_path)

    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path / "img")
    s.general.fullscreen_monitor_index = 7  # 콤보 기본 0 과 달라 setCurrentIndex 시 시그널 유발

    win = MainWindow(s, f)
    qtbot.addWidget(win)

    assert not fake_settings_path.exists(), (
        "MainWindow.__init__ 중에 settings.json 이 디스크에 쓰여졌다. "
        "Qt 위젯 초기 시그널이 _persist_settings 를 발화시킨 회귀."
    )
