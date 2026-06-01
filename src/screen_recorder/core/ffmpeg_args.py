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
        # 키프레임 간격 = 1초. ultrafast 의 기본 GOP(~250 frame ≈ 8초) 가 너무 길어
        # 비키프레임 위치로 시크할 때 디코더가 앞 키프레임까지 거꾸로 가서 다시 디코딩
        # → 진행바 드래그 시 미리보기 갱신이 0.1~0.2s 로 떨어짐. -g {fps} 로 1초마다
        # 키프레임을 강제하면 시크 비용이 ~30× 줄고 파일 크기는 2~5%만 증가.
        "-g", str(max(1, s.fps)),
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
    # -shortest 는 의도적으로 뺀다. 오디오가 영상보다 짧게 캡처된 경우(예: 중간부터
    # 소리가 난 녹화) -shortest 가 영상을 오디오 길이로 잘라버려 영상 손실이 발생한다
    # (실제 사고: 16s 영상이 21ms 로 truncate 될 뻔). 영상이 항상 길이의 기준이 되도록
    # 두면, 오디오가 짧으면 그만큼만 소리가 나고 나머지는 무음(영상은 온전)으로 남는다.
    # 오디오가 영상보다 살짝 긴 경우의 꼬리(수십 ms)는 무시 가능한 cosmetic 차이.
    return [
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-c", "copy",
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
