"""설정 -> ffmpeg argv 변환. 모든 함수는 list[str] 반환."""
from __future__ import annotations
from .settings import VideoSettings, GifSettings, SoundSettings


_CODEC_MAP = {
    "h264": "libx264",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
}


def _scaled_dims(width: int, height: int, percent: int) -> tuple[int, int]:
    factor = max(10, min(100, percent)) / 100.0
    w = max(2, int(width * factor) // 2 * 2)
    h = max(2, int(height * factor) // 2 * 2)
    return w, h


def video_pipe_args(
    s: VideoSettings,
    width: int,
    height: int,
    output: str,
) -> list[str]:
    """stdin으로 BGRA rawvideo 받아 컨테이너로 인코딩."""
    args = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgra",
        "-s", f"{width}x{height}",
        "-r", str(s.fps),
        "-i", "-",
    ]
    if s.scale_percent != 100:
        sw, sh = _scaled_dims(width, height, s.scale_percent)
        args += ["-vf", f"scale={sw}:{sh}:flags=lanczos"]
    args += [
        "-c:v", _CODEC_MAP[s.codec],
        "-preset", "ultrafast",
        "-b:v", f"{s.bitrate_kbps}k",
        "-pix_fmt", "yuv420p",
        output,
    ]
    return args


def audio_encode_args(
    s: SoundSettings,
    raw_input: str,
    sample_rate: int,
    channels: int,
    output: str,
) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-f", "s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-i", raw_input,
        "-c:a", s.codec,
        "-b:a", f"{s.bitrate_kbps}k",
        output,
    ]


def mux_args(video: str, audio: str, output: str) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-c", "copy",
        "-shortest",
        output,
    ]


def gif_palette_args(s: GifSettings, source_video: str, palette_output: str) -> list[str]:
    factor = max(10, min(100, s.scale_percent)) / 100.0
    vf = (
        f"fps={s.fps},"
        f"scale=iw*{factor:g}:ih*{factor:g}:flags=lanczos,"
        f"palettegen=max_colors={s.colors}:stats_mode=diff"
    )
    return [
        "ffmpeg", "-y",
        "-i", source_video,
        "-vf", vf,
        palette_output,
    ]


def gif_apply_args(s: GifSettings, source_video: str, palette: str, output: str) -> list[str]:
    factor = max(10, min(100, s.scale_percent)) / 100.0
    lavfi = (
        f"fps={s.fps},"
        f"scale=iw*{factor:g}:ih*{factor:g}:flags=lanczos [x]; "
        f"[x][1:v] paletteuse=dither=bayer"
    )
    return [
        "ffmpeg", "-y",
        "-i", source_video,
        "-i", palette,
        "-lavfi", lavfi,
        output,
    ]
