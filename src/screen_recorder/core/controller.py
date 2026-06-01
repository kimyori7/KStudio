"""캡처/인코더/단축키를 조립하는 중앙 컨트롤러."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import queue
import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .settings import AppSettings, default_video_dir
from .state import RecorderState, can_transition, InvalidTransition
from .filename import build_filename, resolve_collision
from ..capture.targets import CaptureTarget, Rect
from ..capture.video import VideoCaptureThread
from ..capture.audio import AudioCaptureThread
from ..encode.video_encoder import VideoEncoder
from ..encode.gif_encoder import GifEncoder


class _EvenRectTarget:
    """capture target 래퍼 — current_rect() 의 width/height 를 짝수로 강제.

    libx264 는 YUV420 chroma subsampling 때문에 width/height 가 모두 짝수여야 한다
    (홀수면 `Error while opening encoder` 로 실패 → 0byte mp4). 사용자가 자유롭게
    그린 region 영역은 1388×781 처럼 홀수 차원이 나올 수 있어 캡처 파이프라인 진입
    시점에 짝수로 클램프 (홀수면 1px 잘라냄). label/원본 객체는 그대로 보존.
    """

    def __init__(self, inner: CaptureTarget) -> None:
        self._inner = inner

    def current_rect(self):
        r = self._inner.current_rect()
        if r is None:
            return None
        # 비트마스크로 가장 가까운 작은 짝수로 (1388 → 1388, 781 → 780).
        # 음수나 0 보호: max(0, ...).
        return Rect(r.x, r.y, max(0, r.w & ~1), max(0, r.h & ~1))

    def label(self) -> str:
        return self._inner.label()


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
        # stop_recording 후 백그라운드 daemon 스레드가 mp4/gif finalize 중인지 여부.
        # 앱 종료 시 main_window 가 이 플래그를 보고 finalize 완료까지 modal 로 대기 →
        # daemon 이 도중에 끊겨 손상된 영상이 생기는 것을 방지.
        self._finalizing = False

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
        return default_video_dir()

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
        # h264/x265 등은 짝수 차원만 허용 — 짝수 강제 래퍼로 감싸서
        # 캡처 스레드와 인코더가 같은 (짝수) 해상도를 보게 한다.
        target = _EvenRectTarget(target)
        self._target = target

        rect = target.current_rect()
        if rect is None or rect.w <= 0 or rect.h <= 0:
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
                # 인코더가 mux 전에 캡처 스레드를 join 해 raw flush 를 보장하도록 전달.
                audio_thread=self._audio_thread,
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

        # 캡처 스레드 중단 신호만 보내고 join 은 백그라운드에서 (UI 안 막히게).
        if self._video_thread:
            self._video_thread.stop()
        if self._audio_thread:
            self._audio_thread.stop()
        if self._video_queue is not None:
            # 종료 sentinel 을 큐에 즉시 삽입 — 인코더가 마지막 프레임까지 처리한 뒤
            # stdin 을 닫고 깔끔하게 mp4/gif 헤더를 마무리하게 한다.
            # 주의: queue.put(blocking) 은 가득 찬 큐에서 무한 블록 → UI freeze
            # (UE PIE 처럼 dxcam 이 인코더보다 빨라 큐가 꽉 찬 상태에서 자주 발생).
            # put_nowait 로 시도하고, 가득 차면 한 칸 비우고 다시 put. 메인 스레드는
            # 절대 안 막힘. (sentinel 을 데몬에서 늦게 넣으면 일부 모드에서 인코더 종료
            # 타이밍이 어긋나 파일이 저장되지 않는 회귀가 있어 다시 메인 스레드에서.)
            try:
                self._video_queue.put_nowait(None)
            except queue.Full:
                try:
                    self._video_queue.get_nowait()
                    self._video_queue.put_nowait(None)
                except (queue.Empty, queue.Full):
                    pass

        # 백그라운드에서 join + 결과 emit. 스냅샷 변수로 캡처 (instance 멤버 즉시 nil 가능).
        v_thread = self._video_thread
        a_thread = self._audio_thread
        encoder = self._encoder
        v_queue = self._video_queue
        audio_raw_path = a_thread.output_path if a_thread else None
        out_path = self._output_path

        # 다음 녹화 시작 전 정리 (참조 끊기)
        self._video_thread = None
        self._audio_thread = None
        self._encoder = None
        self._video_queue = None
        self._output_path = None

        self._finalizing = True
        threading.Thread(
            target=self._finalize_stop_async,
            args=(v_thread, a_thread, encoder, v_queue, audio_raw_path, out_path),
            daemon=True,
            name="RecorderStopFinalizer",
        ).start()

    def is_finalizing(self) -> bool:
        """stop_recording 후 mp4/gif 헤더 기록이 끝나기 전 구간인지.
        True 인 동안 앱을 끝내면 손상된 영상이 남는다."""
        return self._finalizing

    def _finalize_stop_async(
        self,
        v_thread,
        a_thread,
        encoder,
        v_queue,
        audio_raw_path,
        out_path,
    ) -> None:
        """백그라운드에서 join + recording_finished emit (UI 스레드 차단 방지)."""
        if v_thread is not None:
            try:
                v_thread.join(timeout=3.0)
            except RuntimeError:
                pass

        # Belt-and-suspenders: 메인 스레드의 put_nowait(None) 가 v_thread 와 경합해
        # 실패한 경우(가득 찬 큐 → drop → 그 사이 v_thread 가 새 프레임 push → 다시 가득 →
        # put_nowait 두 번째 실패) 에 대비. 여기는 v_thread.join 이후라 producer 가 죽었
        # 으니 큐는 줄어들기만 한다. 인코더가 한 프레임 소화할 때까지 짧게 대기하다가
        # 자리가 나면 sentinel 삽입. 1s 내에 거의 항상 성공.
        if v_queue is not None:
            import time as _t
            for _ in range(50):  # 최대 ~1초
                try:
                    v_queue.put_nowait(None)
                    break
                except queue.Full:
                    _t.sleep(0.02)

        if a_thread is not None:
            try:
                a_thread.join(timeout=3.0)
            except RuntimeError:
                pass
        if encoder is not None:
            try:
                encoder.join(timeout=60.0)
            except RuntimeError:
                pass

        if audio_raw_path is not None:
            try:
                Path(audio_raw_path).unlink(missing_ok=True)
            except OSError:
                pass

        # 시그널 emit 전에 플래그를 내려야 — main_window 의 closeEvent 가 _finalizing
        # 을 폴링할 가능성에 대비. (현재는 시그널 기반이지만 의도 명확화 위해 순서 유지.)
        self._finalizing = False
        # 인코더가 self.error 를 남겼으면 사용자에게 그대로 노출 (silent 0초 mp4 방지).
        encoder_error = getattr(encoder, "error", None) if encoder is not None else None
        if encoder_error:
            self.error_occurred.emit(f"녹화 종료 중 문제: {encoder_error}")
        # Qt Signal 은 thread-safe — 자동으로 main thread 슬롯에 dispatch.
        if out_path:
            self.recording_finished.emit(str(out_path))
