from screen_recorder.core.settings import VideoSettings, GifSettings, SoundSettings
from screen_recorder.core.ffmpeg_args import (
    video_pipe_args, audio_encode_args, mux_args, gif_palette_args, gif_apply_args,
)


def test_video_pipe_args_basic():
    s = VideoSettings(container="mp4", codec="h264", fps=30, scale_percent=100, bitrate_kbps=8000)
    args = video_pipe_args(s, width=1920, height=1080, output="out.mp4")
    assert args[0] == "ffmpeg"
    assert "-y" in args
    assert "-f" in args and "rawvideo" in args
    assert "-pix_fmt" in args and "bgra" in args
    assert "-s" in args and "1920x1080" in args
    assert "-r" in args and "30" in args
    assert "-i" in args and "-" in args
    assert "-c:v" in args and "libx264" in args
    assert "-b:v" in args and "8000k" in args
    assert args[-1] == "out.mp4"


def test_video_pipe_args_scale_50():
    s = VideoSettings(scale_percent=50)
    args = video_pipe_args(s, width=1920, height=1080, output="out.mp4")
    vf_idx = args.index("-vf")
    assert "scale=960:540" in args[vf_idx + 1]


def test_video_pipe_args_codec_mapping():
    assert "libx265" in video_pipe_args(VideoSettings(codec="h265"), 100, 100, "x.mp4")
    assert "libvpx-vp9" in video_pipe_args(VideoSettings(codec="vp9"), 100, 100, "x.webm")


def test_audio_encode_args_aac():
    s = SoundSettings(codec="aac", bitrate_kbps=192)
    args = audio_encode_args(s, raw_input="audio.raw", sample_rate=48000, channels=2, output="audio.aac")
    assert "ffmpeg" in args[0]
    assert "-f" in args and "s16le" in args
    assert "-ar" in args and "48000" in args
    assert "-ac" in args and "2" in args
    assert "-c:a" in args and "aac" in args
    assert "-b:a" in args and "192k" in args
    assert args[-1] == "audio.aac"


def test_mux_args_copy_streams():
    args = mux_args(video="video.mp4", audio="audio.aac", output="final.mp4")
    assert "-c" in args and "copy" in args
    assert "video.mp4" in args and "audio.aac" in args
    assert args[-1] == "final.mp4"


def test_gif_palette_args():
    s = GifSettings(fps=10, scale_percent=50, colors=128)
    args = gif_palette_args(s, source_video="src.mp4", palette_output="palette.png")
    vf_idx = args.index("-vf")
    assert "fps=10" in args[vf_idx + 1]
    assert "scale=iw*0.5:ih*0.5" in args[vf_idx + 1]
    assert "palettegen" in args[vf_idx + 1]
    assert "max_colors=128" in args[vf_idx + 1]


def test_gif_apply_args():
    s = GifSettings(fps=10, scale_percent=100, colors=256)
    args = gif_apply_args(s, source_video="src.mp4", palette="palette.png", output="out.gif")
    lavfi_idx = args.index("-lavfi")
    assert "fps=10" in args[lavfi_idx + 1]
    assert "paletteuse" in args[lavfi_idx + 1]
    assert args[-1] == "out.gif"
