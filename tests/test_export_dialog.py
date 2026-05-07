"""export_dialog — 진행 바 + 취소."""
import pytest

from screen_recorder.ui.export_dialog import ExportDialog


def test_export_dialog_progress_updates(qtbot):
    dlg = ExportDialog(total_duration_ms=10000)
    qtbot.addWidget(dlg)
    dlg.set_progress(50)
    assert dlg.progress_bar.value() == 50


def test_export_dialog_cancel_emits(qtbot):
    dlg = ExportDialog(total_duration_ms=10000)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.cancel_requested, timeout=1000):
        dlg.cancel_btn.click()
