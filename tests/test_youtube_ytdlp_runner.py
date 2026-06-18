from pathlib import Path

import pytest

from screen_recorder.youtube.request import DownloadRequest
from screen_recorder.youtube.ytdlp_runner import build_ydl_opts, final_output_path


def _hook(d):
    pass


@pytest.mark.parametrize("mode,quality", [("video", "best"), ("video", "720"), ("mp3", "320")])
def test_opts_accepted_by_real_youtubedl(mode, quality):
    """build_ydl_opts 결과를 실제 yt_dlp.YoutubeDL 이 받아들이는지(옵션명 오타 방지).

    yt-dlp 미설치 환경은 skip. 다운로드는 하지 않고 생성만 한다.
    """
    yt_dlp = pytest.importorskip("yt_dlp")
    req = DownloadRequest("https://example/x", mode, Path("/out"), quality)
    opts = build_ydl_opts(req, ffmpeg_dir=Path("/ff"), progress_hook=_hook)
    with yt_dlp.YoutubeDL(opts):
        pass  # 생성 성공 = 옵션 키/값 형식 유효


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


def test_final_output_path_video_forces_mp4():
    # 회귀: prepare_filename 이 머지 전 컨테이너(.webm)를 줘도 .mp4 로 보정해야 함.
    # (원래 버그: hook 의 조각 파일명을 반환해 .mp4 가 아닌 경로가 나옴 → 이제 prepare_filename 사용)
    base = str(Path("/out") / "Me at the zoo.webm")
    assert final_output_path(base, "video") == str(Path("/out") / "Me at the zoo.mp4")


def test_final_output_path_mp3_forces_mp3():
    base = str(Path("/out") / "Me at the zoo.webm")
    assert final_output_path(base, "mp3") == str(Path("/out") / "Me at the zoo.mp3")
