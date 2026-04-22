"""프레임 큐 -> ffmpeg pipe 영상 인코딩 + 오디오 mux."""
from __future__ import annotations
import queue
import subprocess
import threading
from pathlib import Path
from typing import Optional

from ..core.settings import VideoSettings, SoundSettings
from ..core.ffmpeg_args import video_pipe_args, audio_encode_args, mux_args


class VideoEncoder(threading.Thread):
    """프레임 큐(numpy ndarray 또는 bytes)에서 None을 받으면 종료."""

    def __init__(
        self,
        video_settings: VideoSettings,
        sound_settings: SoundSettings,
        width: int,
        height: int,
        ffmpeg_path: Path,
        output_path: Path,
        frame_queue: queue.Queue,
        audio_raw_path: Optional[Path] = None,
        audio_sample_rate: int = 0,
        audio_channels: int = 0,
    ):
        super().__init__(daemon=True, name="VideoEncoder")
        self.video_settings = video_settings
        self.sound_settings = sound_settings
        self.width = width
        self.height = height
        self.ffmpeg_path = ffmpeg_path
        self.output_path = Path(output_path)
        self.frame_queue = frame_queue
        self.audio_raw_path = audio_raw_path
        self.audio_sample_rate = audio_sample_rate
        self.audio_channels = audio_channels
        self.error: Optional[str] = None

    def run(self) -> None:
        has_audio = (
            self.sound_settings.system_audio_enabled
            and self.audio_raw_path is not None
            and self.audio_sample_rate > 0
        )
        if has_audio:
            video_only = self.output_path.with_suffix(".video.tmp" + self.output_path.suffix)
        else:
            video_only = self.output_path

        argv = video_pipe_args(self.video_settings, self.width, self.height, str(video_only))
        argv[0] = str(self.ffmpeg_path)

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.error = f"ffmpeg start failed: {e}"
            return

        try:
            while True:
                item = self.frame_queue.get()
                if item is None:
                    break
                if proc.poll() is not None:
                    self.error = "ffmpeg exited unexpectedly"
                    break
                data = item if isinstance(item, (bytes, bytearray)) else item.tobytes()
                try:
                    proc.stdin.write(data)
                except (BrokenPipeError, OSError) as e:
                    self.error = f"pipe write failed: {e}"
                    break
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait(timeout=5)

        if not has_audio:
            return

        audio_encoded = self.output_path.with_suffix(".audio.tmp." + self.sound_settings.codec)
        a_argv = audio_encode_args(
            self.sound_settings,
            str(self.audio_raw_path),
            self.audio_sample_rate,
            self.audio_channels,
            str(audio_encoded),
        )
        a_argv[0] = str(self.ffmpeg_path)
        proc_a = subprocess.Popen(a_argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc_a.wait(timeout=30)

        m_argv = mux_args(str(video_only), str(audio_encoded), str(self.output_path))
        m_argv[0] = str(self.ffmpeg_path)
        proc_m = subprocess.Popen(m_argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc_m.wait(timeout=30)

        for p in (video_only, audio_encoded, self.audio_raw_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
