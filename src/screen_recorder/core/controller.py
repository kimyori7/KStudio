"""캡처/인코더/단축키를 조립하는 중앙 컨트롤러."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import queue
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .settings import AppSettings
from .state import RecorderState, can_transition, InvalidTransition
from .filename import build_filename, resolve_collision
from ..capture.targets import CaptureTarget
from ..capture.video import VideoCaptureThread
from ..capture.audio import AudioCaptureThread
from ..encode.video_encoder import VideoEncoder
from ..encode.gif_encoder import GifEncoder


class RecorderController(QObject):
    state_changed = Signal(object)
    error_occurred = Signal(str)
    recording_finished = Signal(str)

    VIDEO_QUEUE_MAX = 60

    def __init__(self, settings: AppSettings, ffmpeg_path: Path):
        super().__init__()
        self.settings = settings
        self.ffmpeg_path = ffmpeg_path
        self._state = RecorderState.IDLE
        self._target: Optional[CaptureTarget] = None
        self._video_thread: Optional[VideoCaptureThread] = None
        self._audio_thread: Optional[AudioCaptureThread] = None
        self._encoder = None
        self._video_queue: Optional[queue.Queue] = None
        self._output_path: Optional[Path] = None

    @property
    def state(self) -> RecorderState:
        return self._state

    def _set_state(self, new: RecorderState) -> None:
        if not can_transition(self._state, new):
            raise InvalidTransition(self._state, new)
        self._state = new
        self.state_changed.emit(new)

    def _output_dir(self) -> Path:
        if self.settings.general.output_dir:
            return Path(self.settings.general.output_dir)
        return Path.home() / "Videos" / "ScreenRecorder"

    def _build_output_path(self, mode: str, target_label: str, extension: str) -> Path:
        out_dir = self._output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = build_filename(
            pattern=self.settings.general.filename_pattern,
            when=datetime.now(),
            mode=mode,
            target=target_label,
            extension=extension,
        )
        return resolve_collision(out_dir / name)

    def start_recording(self, target: CaptureTarget) -> None:
        self._set_state(RecorderState.RECORDING)
        self._target = target

        rect = target.current_rect()
        if rect is None:
            self._set_state(RecorderState.IDLE)
            self.error_occurred.emit("Capture target unavailable")
            return

        mode = self.settings.general.mode
        ext = "gif" if mode == "gif" else self.settings.video.container
        self._output_path = self._build_output_path(mode, target.label(), ext)

        self._video_queue = queue.Queue(maxsize=self.VIDEO_QUEUE_MAX)

        if mode == "gif":
            self._video_thread = VideoCaptureThread(target, self.settings.gif.fps, self._video_queue)
            self._encoder = GifEncoder(
                gif_settings=self.settings.gif,
                width=rect.w, height=rect.h,
                ffmpeg_path=self.ffmpeg_path,
                output_path=self._output_path,
                frame_queue=self._video_queue,
            )
        else:
            self._video_thread = VideoCaptureThread(target, self.settings.video.fps, self._video_queue)
            audio_raw = None
            audio_sr = 0
            audio_ch = 0
            if self.settings.sound.system_audio_enabled:
                audio_raw = self._output_path.with_suffix(".audio.raw")
                self._audio_thread = AudioCaptureThread(audio_raw)
                self._audio_thread.start()
                import time as _t
                _t.sleep(0.1)
                audio_sr = self._audio_thread.sample_rate
                audio_ch = self._audio_thread.channels
            self._encoder = VideoEncoder(
                video_settings=self.settings.video,
                sound_settings=self.settings.sound,
                width=rect.w, height=rect.h,
                ffmpeg_path=self.ffmpeg_path,
                output_path=self._output_path,
                frame_queue=self._video_queue,
                audio_raw_path=audio_raw,
                audio_sample_rate=audio_sr,
                audio_channels=audio_ch,
            )

        self._encoder.start()
        self._video_thread.start()

    def pause_recording(self) -> None:
        self._set_state(RecorderState.PAUSED)
        if self._video_thread:
            self._video_thread.stop()

    def resume_recording(self) -> None:
        self._set_state(RecorderState.RECORDING)
        rect = self._target.current_rect() if self._target else None
        if rect is not None and self._video_queue is not None:
            self._video_thread = VideoCaptureThread(
                self._target,
                self.settings.video.fps if self.settings.general.mode != "gif" else self.settings.gif.fps,
                self._video_queue,
            )
            self._video_thread.start()

    def stop_recording(self) -> None:
        if self._state == RecorderState.IDLE:
            return
        self._set_state(RecorderState.IDLE)

        if self._video_thread:
            self._video_thread.stop()
            self._video_thread.join(timeout=3.0)
        if self._audio_thread:
            self._audio_thread.stop()
            self._audio_thread.join(timeout=3.0)
        if self._video_queue is not None:
            self._video_queue.put(None)
        if self._encoder:
            self._encoder.join(timeout=60.0)

        if self._output_path:
            self.recording_finished.emit(str(self._output_path))

        self._video_thread = None
        self._audio_thread = None
        self._encoder = None
        self._video_queue = None
