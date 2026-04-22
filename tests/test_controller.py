import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState, InvalidTransition
from screen_recorder.capture.targets import RegionTarget, Rect


@pytest.fixture
def controller(tmp_path):
    settings = AppSettings()
    settings.general.output_dir = str(tmp_path)
    return RecorderController(settings=settings, ffmpeg_path=Path("ffmpeg"))


def test_initial_state_is_idle(controller):
    assert controller.state == RecorderState.IDLE


def test_start_recording_changes_state(controller):
    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread") as AC, \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock()
        AC.return_value = MagicMock()
        VE.return_value = MagicMock()
        controller.start_recording(target)
    assert controller.state == RecorderState.RECORDING


def test_double_start_raises(controller):
    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread"), \
         patch("screen_recorder.core.controller.AudioCaptureThread"), \
         patch("screen_recorder.core.controller.VideoEncoder"):
        controller.start_recording(target)
        with pytest.raises(InvalidTransition):
            controller.start_recording(target)


def test_gif_mode_uses_gif_encoder(controller):
    controller.settings.general.mode = "gif"
    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread"), \
         patch("screen_recorder.core.controller.GifEncoder") as GE, \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        GE.return_value = MagicMock()
        controller.start_recording(target)
        GE.assert_called_once()
        VE.assert_not_called()


def test_stop_returns_to_idle(controller):
    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread") as AC, \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock()
        AC.return_value = MagicMock()
        VE.return_value = MagicMock()
        controller.start_recording(target)
        controller.stop_recording()
    assert controller.state == RecorderState.IDLE
