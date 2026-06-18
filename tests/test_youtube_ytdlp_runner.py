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


def test_run_download_sets_pp_hooks_and_converts_cancel(monkeypatch):
    """취소(DownloadCancelled)가 CancelledError 로 변환되고, postprocessor_hooks 가
    설정되는지(=후처리 단계 취소 확인 경로) 검증. 실제 다운로드/네트워크 없음."""
    import pytest
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
    from screen_recorder.youtube import ytdlp_runner as r

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            raise DownloadCancelled()   # 후처리/다운로드 중 취소 흉내

        def prepare_filename(self, info):
            return "x"

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    req = DownloadRequest("u", "mp3", Path("/o"), "192")
    with pytest.raises(r.CancelledError):
        r.run_download(req, Path("/ff"), lambda d: None, lambda: True)
    assert "postprocessor_hooks" in captured["opts"]
    assert captured["opts"]["postprocessor_hooks"]   # 비어있지 않음
