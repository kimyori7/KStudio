"""프레임 큐 -> 임시 영상 -> 2-pass GIF 인코딩."""
from __future__ import annotations
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from ..core.settings import GifSettings, VideoSettings
from ..core.ffmpeg_args import video_pipe_args, gif_palette_args, gif_apply_args


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class GifEncoder(threading.Thread):
    def __init__(
        self,
        gif_settings: GifSettings,
        width: int,
        height: int,
        ffmpeg_path: Path,
        output_path: Path,
        frame_queue: queue.Queue,
    ):
        super().__init__(daemon=True, name="GifEncoder")
        self.gif_settings = gif_settings
        self.width = width
        self.height = height
        self.ffmpeg_path = ffmpeg_path
        self.output_path = Path(output_path)
        self.frame_queue = frame_queue
        self.error: Optional[str] = None

    def run(self) -> None:
        temp_video = self.output_path.with_suffix(".source.tmp.mp4")
        palette = self.output_path.with_suffix(".palette.tmp.png")

        v_settings = VideoSettings(container="mp4", codec="h264", fps=self.gif_settings.fps,
                                   scale_percent=100, bitrate_kbps=20000)
        argv = video_pipe_args(v_settings, self.width, self.height, str(temp_video))
        argv[0] = str(self.ffmpeg_path)

        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
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
                    self.error = "ffmpeg exited"
                    break
                data = item if isinstance(item, (bytes, bytearray)) else item.tobytes()
                try:
                    proc.stdin.write(data)
                except (BrokenPipeError, OSError) as e:
                    self.error = str(e)
                    break
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait(timeout=5)

        p_argv = gif_palette_args(self.gif_settings, str(temp_video), str(palette))
        p_argv[0] = str(self.ffmpeg_path)
        subprocess.Popen(
            p_argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        ).wait(timeout=60)

        g_argv = gif_apply_args(self.gif_settings, str(temp_video), str(palette), str(self.output_path))
        g_argv[0] = str(self.ffmpeg_path)
        subprocess.Popen(
            g_argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        ).wait(timeout=60)

        for p in (temp_video, palette):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
