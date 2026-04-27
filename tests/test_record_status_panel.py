from screen_recorder.core.state import RecorderState
from screen_recorder.ui.docks.record_status_panel import RecordStatusPanel


def test_initial_state_idle(qtbot):
    p = RecordStatusPanel()
    qtbot.addWidget(p)
    assert "대기" in p.state_label.text()


def test_set_state_recording(qtbot):
    p = RecordStatusPanel()
    qtbot.addWidget(p)
    p.set_state(RecorderState.RECORDING)
    assert "녹화" in p.state_label.text()


def test_set_target_text(qtbot):
    p = RecordStatusPanel()
    qtbot.addWidget(p)
    p.set_target("fullscreen")
    assert "전체화면" in p.target_label.text()
