"""Test update prompt UI and download progress dialog."""
from screen_recorder.app.updater.manifest import Manifest
from screen_recorder.ui.update_prompt import DownloadProgressDialog

_M = Manifest(version="0.1.5", notes="버그픽스 묶음",
              full_url="https://x/Setup.exe", full_sha256="a" * 64)


def test_progress_dialog_updates(qtbot):
    dlg = DownloadProgressDialog("0.1.5")
    qtbot.addWidget(dlg)
    dlg.set_progress(50, 100)
    assert dlg.value() == 50
    dlg.set_progress(100, 100)
    assert dlg.value() == 100


def test_progress_dialog_busy_when_total_zero(qtbot):
    dlg = DownloadProgressDialog("0.1.5")
    qtbot.addWidget(dlg)
    dlg.set_progress(1234, 0)        # total 모름 → 예외 없이 동작(busy)
    assert dlg.maximum() == 0        # busy 인디케이터
