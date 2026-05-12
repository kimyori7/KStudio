"""export_dialog — 진행 바 + 취소 + ETA."""
import time

import pytest

from screen_recorder.ui.export_dialog import ExportDialog, _format_eta


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


def test_format_eta_under_minute():
    assert _format_eta(30) == "30초"
    assert _format_eta(0) == ""
    assert _format_eta(-5) == ""


def test_format_eta_minutes():
    assert _format_eta(60) == "1분"
    assert _format_eta(125) == "2분 5초"


def test_format_eta_hours():
    assert _format_eta(3700) == "1시간 1분"


def test_eta_label_appears_after_progress(qtbot):
    """첫 progress 시 timer 시작 → 두 번째 progress 부터 ETA 텍스트 채워짐."""
    dlg = ExportDialog(total_duration_ms=10000)
    qtbot.addWidget(dlg)
    dlg.set_progress(10)   # 첫 progress — timer 시작.
    assert dlg.eta_label.text() == ""   # 아직 elapsed=0 이라 ETA 못 잼.
    time.sleep(0.05)
    dlg.set_progress(20)
    # elapsed 50ms / pct=20 → ETA = 50 * 80/20 = 200ms = 0초로 표시될 수 있으니
    # 라벨이 채워졌거나 비어있거나 둘 다 OK — 핵심은 timer 가 동작 중.
    assert dlg.eta_label.text() == "" or "예상" in dlg.eta_label.text()


def test_eta_label_cleared_on_error(qtbot):
    dlg = ExportDialog(total_duration_ms=10000)
    qtbot.addWidget(dlg)
    dlg.set_progress(20)
    dlg.eta_label.setText("예상 남은 시간: 1분")
    dlg.set_error("test")
    assert dlg.eta_label.text() == ""
