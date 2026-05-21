"""ModelDownloadJob 단위 테스트 — snapshot_download mock + Signal 발행."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def test_download_emits_finished_on_success(qtbot, monkeypatch):
    """snapshot_download 정상 종료 → finished Signal."""
    import sys
    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(return_value="/fake/local/path")
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    from screen_recorder.agent.models.downloader import ModelDownloadJob

    job = ModelDownloadJob(repo_id="Qwen/Qwen2.5-Omni-7B")
    finished_calls = []
    job.finished.connect(lambda repo: finished_calls.append(repo))

    with qtbot.waitSignal(job.finished, timeout=3000):
        job.start()

    assert finished_calls == ["Qwen/Qwen2.5-Omni-7B"]
    fake_hub.snapshot_download.assert_called_once()
    call_kwargs = fake_hub.snapshot_download.call_args.kwargs
    assert call_kwargs.get("repo_id") == "Qwen/Qwen2.5-Omni-7B"


def test_download_emits_error_on_failure(qtbot, monkeypatch):
    """snapshot_download raise → error Signal."""
    import sys
    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(side_effect=RuntimeError("network fail"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    from screen_recorder.agent.models.downloader import ModelDownloadJob

    job = ModelDownloadJob(repo_id="Qwen/Qwen2.5-Omni-7B")
    error_calls = []
    job.error.connect(lambda msg: error_calls.append(msg))

    with qtbot.waitSignal(job.error, timeout=3000):
        job.start()

    assert len(error_calls) == 1
    assert "network fail" in error_calls[0]


def test_download_emits_progress_when_polling(qtbot, monkeypatch, tmp_path):
    """cache dir 크기 polling — progress Signal 발행."""
    import sys, time, threading
    cache_dir = tmp_path / "models--Qwen--Qwen2.5-Omni-7B"
    cache_dir.mkdir()

    def _slow_download(**kwargs):
        (cache_dir / "file1.bin").write_bytes(b"x" * 1024)
        time.sleep(0.05)
        (cache_dir / "file2.bin").write_bytes(b"y" * 2048)
        time.sleep(0.05)
        return str(cache_dir)

    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(side_effect=_slow_download)
    fake_constants = MagicMock()
    fake_constants.HF_HUB_CACHE = str(tmp_path)
    fake_hub.constants = fake_constants
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", fake_constants)

    from screen_recorder.agent.models.downloader import ModelDownloadJob

    job = ModelDownloadJob(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        estimated_size_bytes=3072,
        poll_interval_ms=20,
    )
    progress_calls = []
    job.download_progress.connect(lambda r, t: progress_calls.append((r, t)))

    with qtbot.waitSignal(job.finished, timeout=3000):
        job.start()

    assert len(progress_calls) >= 1
    for r, t in progress_calls:
        assert t == 3072
        assert r >= 0
