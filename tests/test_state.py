import pytest

from screen_recorder.core.state import RecorderState, can_transition, InvalidTransition


def test_initial_state_is_idle():
    assert RecorderState.IDLE.name == "IDLE"


@pytest.mark.parametrize("frm,to", [
    (RecorderState.IDLE, RecorderState.RECORDING),
    (RecorderState.RECORDING, RecorderState.PAUSED),
    (RecorderState.RECORDING, RecorderState.IDLE),
    (RecorderState.PAUSED, RecorderState.RECORDING),
    (RecorderState.PAUSED, RecorderState.IDLE),
])
def test_allowed_transitions(frm, to):
    assert can_transition(frm, to) is True


@pytest.mark.parametrize("frm,to", [
    (RecorderState.IDLE, RecorderState.PAUSED),
    (RecorderState.IDLE, RecorderState.IDLE),
    (RecorderState.RECORDING, RecorderState.RECORDING),
    (RecorderState.PAUSED, RecorderState.PAUSED),
])
def test_disallowed_transitions(frm, to):
    assert can_transition(frm, to) is False


def test_invalid_transition_exception_message():
    err = InvalidTransition(RecorderState.IDLE, RecorderState.PAUSED)
    assert "IDLE" in str(err) and "PAUSED" in str(err)
