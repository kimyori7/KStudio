from pathlib import Path

from screen_recorder.youtube.request import DownloadRequest


def test_download_request_fields():
    req = DownloadRequest(url="https://y", mode="mp3", out_dir=Path("/d"), quality="320")
    assert req.url == "https://y"
    assert req.mode == "mp3"
    assert req.out_dir == Path("/d")
    assert req.quality == "320"
