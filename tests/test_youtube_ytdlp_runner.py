from pathlib import Path

from screen_recorder.youtube.request import DownloadRequest
from screen_recorder.youtube.ytdlp_runner import build_ydl_opts


def _hook(d):
    pass


def test_video_best_opts():
    req = DownloadRequest("u", "video", Path("/out"), "best")
    o = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    assert o["noplaylist"] is True
    assert o["merge_output_format"] == "mp4"
    assert o["format"] == "bestvideo+bestaudio/best"
    assert str(Path("/out")) in o["outtmpl"]
    assert o["ffmpeg_location"] == str(Path("/ff"))
    assert "postprocessors" not in o or not o["postprocessors"]


def test_video_720_opts():
    req = DownloadRequest("u", "video", Path("/out"), "720")
    o = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    assert o["format"] == "bestvideo[height<=720]+bestaudio/best[height<=720]"


def test_video_unknown_quality_falls_back_to_best():
    req = DownloadRequest("u", "video", Path("/out"), "weird")
    o = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    assert o["format"] == "bestvideo+bestaudio/best"


def test_mp3_opts():
    req = DownloadRequest("u", "mp3", Path("/out"), "320")
    o = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    assert o["format"] == "bestaudio/best"
    assert "merge_output_format" not in o
    pp = o["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "320"


def test_progress_hook_registered():
    req = DownloadRequest("u", "mp3", Path("/out"), "192")
    o = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    assert o["progress_hooks"] == [_hook]
