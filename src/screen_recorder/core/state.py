"""녹화 상태 머신."""
from enum import Enum, auto


class RecorderState(Enum):
    IDLE = auto()
    RECORDING = auto()
    PAUSED = auto()


_ALLOWED = {
    (RecorderState.IDLE, RecorderState.RECORDING),
    (RecorderState.RECORDING, RecorderState.PAUSED),
    (RecorderState.RECORDING, RecorderState.IDLE),
    (RecorderState.PAUSED, RecorderState.RECORDING),
    (RecorderState.PAUSED, RecorderState.IDLE),
}


def can_transition(frm: RecorderState, to: RecorderState) -> bool:
    return (frm, to) in _ALLOWED


class InvalidTransition(RuntimeError):
    def __init__(self, frm: RecorderState, to: RecorderState):
        super().__init__(f"Invalid state transition: {frm.name} -> {to.name}")
        self.frm = frm
        self.to = to
