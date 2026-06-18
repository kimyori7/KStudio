from pathlib import Path

from screen_recorder.youtube.request import DownloadRequest
from screen_recorder.youtube.download_job import YouTubeDownloadJob
from screen_recorder.youtube import ytdlp_runner


def test_job_finished_emits_path(qtbot):
    captured = {}

    def fake_run(req, ffmpeg_dir, progress_hook, cancel_check):
        progress_hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        return "C:/out/video.mp4"

    req = DownloadRequest("u", "video", Path("C:/out"), "best")
    job = YouTubeDownloadJob(req, ffmpeg_dir=Path("C:/ff"), runner=fake_run)
    job.finished.connect(lambda p: captured.setdefault("path", p))
    with qtbot.waitSignal(job.finished, timeout=3000):
        job.start()
    assert captured["path"] == "C:/out/video.mp4"


def test_job_error_emits_message(qtbot):
    captured = {}

    def fake_run(req, ffmpeg_dir, progress_hook, cancel_check):
        raise RuntimeError("boom")

    req = DownloadRequest("u", "mp3", Path("C:/out"), "192")
    job = YouTubeDownloadJob(req, ffmpeg_dir=Path("C:/ff"), runner=fake_run)
    job.error.connect(lambda m: captured.setdefault("msg", m))
    with qtbot.waitSignal(job.error, timeout=3000):
        job.start()
    assert "boom" in captured["msg"]


def test_job_cancel_emits_cancelled(qtbot):
    def fake_run(req, ffmpeg_dir, progress_hook, cancel_check):
        # 취소 플래그가 켜졌으면 runner 가 CancelledError 를 던지는 것을 흉내.
        if cancel_check():
            raise ytdlp_runner.CancelledError()
        return "x"

    req = DownloadRequest("u", "mp3", Path("C:/out"), "192")
    job = YouTubeDownloadJob(req, ffmpeg_dir=Path("C:/ff"), runner=fake_run)
    job.cancel()  # start 전에 취소 플래그 set
    with qtbot.waitSignal(job.cancelled, timeout=3000):
        job.start()
