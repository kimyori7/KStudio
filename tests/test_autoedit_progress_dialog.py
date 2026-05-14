from PySide6.QtCore import Qt
from screen_recorder.ui.autoedit.progress_dialog import AutoEditProgressDialog


def test_progress_dialog_updates_label_and_bar(qtbot):
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    d.update_progress("자막 (2/4)", 0.5)
    assert "자막" in d.label().text()
    assert d.bar().value() == 50


def test_cancel_emits_signal(qtbot):
    d = AutoEditProgressDialog(parent=None)
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.cancelled, timeout=1000):
        d.cancel_button().click()
