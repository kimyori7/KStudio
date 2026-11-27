import logging
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from screen_recorder.core.controller import RecorderController
from screen_recorder.core.settings import AppSettings
from screen_recorder.core.state import RecorderState, InvalidTransition
from screen_recorder.capture.targets import RegionTarget, Rect


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.setattr("screen_recorder.core.controller.resolve_output_rects", lambda: [])
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


def test_controller_waits_for_delayed_audio_format(controller):
    class DelayedAudioCapture(threading.Thread):
        def __init__(self, output_path):
            super().__init__(daemon=True)
            self.output_path = output_path
            self.ready = threading.Event()
            self.sample_rate = self.channels = 0
            self.error = None

        def run(self):
            time.sleep(0.3)
            self.sample_rate = 48000
            self.channels = 2
            self.ready.set()

    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread"), \
         patch("screen_recorder.core.controller.AudioCaptureThread", DelayedAudioCapture), \
         patch("screen_recorder.core.controller.VideoEncoder") as encoder:
        controller.start_recording(target)
        controller.pause_recording()
        controller.resume_recording()

    encoder.assert_called_once()
    args = encoder.call_args.kwargs
    assert args["audio_raw_path"].suffix == ".raw"
    assert args["audio_sample_rate"] == 48000
    assert args["audio_channels"] == 2
    assert args["audio_start_error"] is None


@pytest.mark.parametrize("failure", ["device", "timeout", "thread"])
def test_controller_reports_audio_startup_failure_after_stop(
    controller, qtbot, caplog, failure, tmp_path,
):
    controller.AUDIO_READY_TIMEOUT = 0.02
    audio = MagicMock()
    audio.ready = threading.Event()
    audio.output_path = tmp_path / "audio.raw"
    if failure == "device":
        audio.error = "loopback unavailable"
        audio.ready.set()
        expected_reason = "loopback unavailable"
    elif failure == "timeout":
        expected_reason = "시간 초과"
    else:
        audio.start.side_effect = RuntimeError("cannot start thread")
        expected_reason = "cannot start thread"

    proc = MagicMock()
    proc.poll.return_value = None
    proc.returncode = 0

    def fake_popen(argv, **kwargs):
        Path(argv[-1]).write_bytes(b"video")
        return proc

    def fake_video_capture(target, fps, frame_queue):
        capture = MagicMock()
        capture.start.side_effect = lambda: frame_queue.put(b"frame")
        return capture

    errors = []
    controller.error_occurred.connect(errors.append)
    target = RegionTarget(Rect(0, 0, 100, 100))
    with caplog.at_level(logging.WARNING), \
         patch("screen_recorder.core.controller.VideoCaptureThread", side_effect=fake_video_capture), \
         patch("screen_recorder.core.controller.AudioCaptureThread", return_value=audio), \
         patch("screen_recorder.encode.video_encoder.subprocess", wraps=subprocess) as encoder_subprocess:
        encoder_subprocess.Popen.side_effect = fake_popen
        controller.start_recording(target)
        assert errors == []
        audio.stop.assert_called_once()
        with qtbot.waitSignal(controller.recording_finished, timeout=5000) as finished:
            controller.stop_recording()

    encoder_subprocess.Popen.assert_called_once()
    assert Path(finished.args[0]).read_bytes() == b"video"
    assert len(errors) == 1
    assert "소리를 넣지 못했습니다" in errors[0]
    assert expected_reason in errors[0]
    assert any(
        record.levelno == logging.WARNING
        and "audio startup failed" in record.message
        and expected_reason in record.message
        for record in caplog.records
    )


# ----- 영역의 화면 밖/걸침 처리 (2026-06-09 빈 영상 사고 → 멀티모니터 합성으로 진화) -----

def _two_monitors():
    """2560x1440 모니터 2개(x=0, x=2560) 의 output 사각형 (위치 기반 매핑)."""
    from screen_recorder.capture.video import _OutputRect
    return [
        _OutputRect(0, 0, 0, 0, 2560, 1440),
        _OutputRect(0, 1, 2560, 0, 5120, 1440),
    ]


def test_start_allows_region_spanning_two_monitors(controller):
    """두 모니터에 걸친 영역(x=700, w=3638)은 이제 output 별 카메라를 합성해 녹화한다
    — 더 이상 막지 않는다(이전 '빈 mp4' 사고는 합성 미구현이라서였다)."""
    target = RegionTarget(Rect(700, 100, 3638, 1270))  # 2560 경계를 넘김 (양쪽 모두 모니터 위)
    with patch("screen_recorder.core.controller.resolve_output_rects",
               return_value=_two_monitors()), \
         patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread"), \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock(); VE.return_value = MagicMock()
        controller.start_recording(target)
    assert controller.state == RecorderState.RECORDING


def test_start_rejects_region_partly_off_screen(controller):
    """영역의 일부가 어떤 모니터에도 없으면(오른쪽 끝이 5120 너머) 그 부분은 검은색
    으로만 찍히므로 시작 전에 막는다."""
    target = RegionTarget(Rect(4800, 100, 800, 800))  # 5120 경계를 넘어 화면 밖으로
    with patch("screen_recorder.core.controller.resolve_output_rects",
               return_value=_two_monitors()), \
         patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        with pytest.raises(ValueError) as ei:
            controller.start_recording(target)
        VC.assert_not_called()
        VE.assert_not_called()
    assert "화면 밖" in str(ei.value)
    assert controller.state == RecorderState.IDLE  # 상태도 안 바뀌어야 함


def test_start_allows_region_within_one_monitor(controller):
    target = RegionTarget(Rect(100, 100, 1200, 800))  # 모니터 0 안에 완전히 포함
    with patch("screen_recorder.core.controller.resolve_output_rects",
               return_value=_two_monitors()), \
         patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread"), \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock(); VE.return_value = MagicMock()
        controller.start_recording(target)
    assert controller.state == RecorderState.RECORDING


def test_start_allows_region_on_second_monitor(controller):
    """둘째 모니터(x=2560~) 안의 영역도 정상."""
    target = RegionTarget(Rect(2700, 100, 1200, 800))  # 모니터 1 안
    with patch("screen_recorder.core.controller.resolve_output_rects",
               return_value=_two_monitors()), \
         patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread"), \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock(); VE.return_value = MagicMock()
        controller.start_recording(target)
    assert controller.state == RecorderState.RECORDING


# ----- 오디오 없음은 팝업이 아니라 조용한 notice (사용자 요청 2026-06-09) -----

def test_audio_absent_notice_does_not_emit_error(controller):
    """인코더가 error 없이 notice(오디오 없음)만 남기면 녹화 종료 시 error_occurred
    (= 팝업)을 내지 않는다. 영상은 정상 저장됐으므로 굳이 막아 세우지 않는다."""
    errors = []
    controller.error_occurred.connect(lambda m: errors.append(m))
    fake_enc = MagicMock()
    fake_enc.error = None
    fake_enc.notice = "영상은 저장됐지만 오디오는 캡처된 소리가 없어 제외했습니다."
    controller._finalize_stop_async(None, None, fake_enc, None, None, "out.mp4")
    assert errors == []


def test_real_encoder_error_still_emits_error(controller):
    """진짜 실패(캡처 실패 등)는 여전히 error_occurred → 팝업."""
    errors = []
    controller.error_occurred.connect(lambda m: errors.append(m))
    fake_enc = MagicMock()
    fake_enc.error = "화면 캡처에 실패해 영상이 저장되지 않았습니다 — 프레임을 받지 못했습니다."
    fake_enc.notice = None
    controller._finalize_stop_async(None, None, fake_enc, None, None, "out.mp4")
    assert len(errors) == 1
    assert "캡처" in errors[0]


# ----- capture_stopped (메인 창이 캡처 제외 플래그를 풀어도 되는 시점) -----

def test_capture_stopped_emitted_once_after_stop(qtbot, controller):
    """정상 정지: finalizer 스레드가 캡처 스레드를 join 한 직후, 시작 한 번당 정확히 1회.

    capture_stopped 는 recording_finished(인코딩 완료) 와 별개 사건 — IDLE 전이에서
    풀면 마지막 프레임에 창이 찍히므로, 캡처 스레드가 실제로 멈춘 뒤에 나야 한다."""
    calls = []
    controller.capture_stopped.connect(lambda: calls.append(1))
    target = RegionTarget(Rect(0, 0, 100, 100))
    with patch("screen_recorder.core.controller.VideoCaptureThread") as VC, \
         patch("screen_recorder.core.controller.AudioCaptureThread") as AC, \
         patch("screen_recorder.core.controller.VideoEncoder") as VE:
        VC.return_value = MagicMock()
        AC.return_value = MagicMock()
        VE.return_value = MagicMock()
        controller.start_recording(target)
        # finalizer 는 백그라운드 스레드 — Qt 시그널이 스레드 안전이므로 메인 스레드
        # 이벤트 루프로 dispatch 된다. 다만 MagicMock join 이라 finalizer 가 stop() 보다
        # 먼저 끝날 수 있어, 블로커를 먼저 걸고 stop 을 그 안에서 부른다 (레이스 방지).
        with qtbot.waitSignal(controller.capture_stopped, timeout=5000):
            controller.stop_recording()
    assert len(calls) == 1


def test_capture_stopped_emitted_on_unavailable_target(controller):
    """시작 실패(target unavailable): IDLE 복귀 직후 정확히 1회.

    여기선 인코딩이 아예 시작되지 않았으므로 recording_finished 는 안 나고,
    capture_stopped 만 나야 한다 (메인 창이 걸었던 플래그를 풀 책임)."""
    calls = []
    controller.capture_stopped.connect(lambda: calls.append(1))
    target = MagicMock()
    target.current_rect.return_value = None
    controller.start_recording(target)
    assert controller.state == RecorderState.IDLE
    assert len(calls) == 1
