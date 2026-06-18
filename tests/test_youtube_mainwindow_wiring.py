"""유튜브 기능의 MainWindow 배선 통합 검증 — 패널 삽입 + 메뉴 핸들러 + 작업 시작.

실제 네트워크/yt-dlp 없이: 다이얼로그를 가짜로 바꿔 즉시 accept, runner 도 가짜로 주입.
"""
from pathlib import Path

import pytest

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow


@pytest.fixture
def win(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    w = MainWindow(s, f)
    qtbot.addWidget(w)
    return w


def test_downloads_button_exists_and_hidden(win):
    # 다운로드 버튼은 글로벌 툴바(설정 버튼 왼쪽)에 있고, 작업 0개면 숨김.
    btn = win.global_toolbar.downloads_button
    assert btn is not None
    assert btn.isHidden()


def test_open_youtube_dialog_remembers_dir_and_quality(win, qtbot, tmp_path, monkeypatch):
    out = tmp_path / "ytout"

    from screen_recorder.youtube.request import DownloadRequest

    class FakeDialog:
        def __init__(self, mode, start_dir, start_quality, parent=None):
            self._mode = mode

        def exec(self):
            return 1   # QDialog.Accepted == 1

        def build_request(self):
            return DownloadRequest("https://y/x", self._mode, out, "720")

        def selected_dir(self):
            return str(out)

        def selected_quality(self):
            return "720"

    # _open_youtube_dialog 가 함수 내부에서 import 하므로 모듈 속성을 교체하면 잡힌다.
    monkeypatch.setattr(
        "screen_recorder.ui.youtube.download_dialog.YouTubeDownloadDialog",
        FakeDialog,
    )

    # 작업 시작은 가로채서 네트워크/스레드 안 띄움 — 폴더·품질 기억 + 요청 전달만 확인.
    started = {}

    def fake_start(req, ffmpeg_dir):
        started["req"] = req
        started["ffmpeg_dir"] = ffmpeg_dir

    monkeypatch.setattr(win, "_start_youtube_job", fake_start)

    win._open_youtube_dialog("video")

    assert started["req"].mode == "video"
    assert started["req"].quality == "720"
    assert win.app_settings.youtube.video_dir == str(out)
    assert win.app_settings.youtube.video_quality == "720"
