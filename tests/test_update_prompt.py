"""Test update prompt UI and download progress dialog.

prompt_update 의 모달 버튼 결과는 수동검증(헤드리스 모달 클릭 위조 금지) — 여기선
DownloadProgressDialog 의 진행/busy 동작만 자동 검증한다.
"""
from screen_recorder.ui.update_prompt import DownloadProgressDialog


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
