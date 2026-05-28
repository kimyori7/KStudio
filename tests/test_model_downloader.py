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


def test_download_emits_immediate_progress_for_resume_scenario(qtbot, monkeypatch, tmp_path):
    """캐시에 이미 일부 파일이 있을 때 — start() 직후 즉시 progress emit.

    2026-05-21 사용자 보고 시나리오: KStudio 재시작 후 Qwen 클릭 → snapshot_download
    가 빠르게 끝남 (대부분 캐시 hit) → 폴링이 늦으면 사용자에게 "안 움직임" 으로 보임.
    start() 가 첫 poll 을 즉시 실행해 받은 바이트 수 (이미 캐시된 부분 포함) 가
    표시되도록 한다.
    """
    import sys
    cache_dir = tmp_path / "models--Qwen--Qwen2.5-Omni-7B"
    cache_dir.mkdir()
    # 이미 캐시된 파일 — start() 전 디스크에 존재.
    (cache_dir / "existing.bin").write_bytes(b"z" * 5000)

    fake_hub = MagicMock()
    # snapshot_download 은 즉시 끝남 (할 일 없음 — 캐시 완료 시나리오).
    fake_hub.snapshot_download = MagicMock(return_value=str(cache_dir))
    fake_constants = MagicMock()
    fake_constants.HF_HUB_CACHE = str(tmp_path)
    fake_hub.constants = fake_constants
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", fake_constants)

    from screen_recorder.agent.models.downloader import ModelDownloadJob

    job = ModelDownloadJob(
        repo_id="Qwen/Qwen2.5-Omni-7B",
        estimated_size_bytes=10000,
        poll_interval_ms=2000,  # 큰 간격 — 즉시 emit 안 하면 finished 전에 progress 0건.
    )
    progress_calls: list = []
    job.download_progress.connect(lambda r, t: progress_calls.append((r, t)))

    with qtbot.waitSignal(job.finished, timeout=3000):
        job.start()

    # start() 가 즉시 poll → 캐시된 5000 byte 가 보고됨.
    assert len(progress_calls) >= 1, "start() 직후 progress 가 한 번도 안 emit 됨"
    # 첫 emit 이 5000 byte 표시 (캐시 hit 반영).
    first_received, first_total = progress_calls[0]
    assert first_received >= 5000, (
        f"첫 progress 가 캐시된 양 반영 못함: received={first_received}"
    )
    assert first_total == 10000


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
    # 마지막 progress 는 _on_worker_done 의 100% 강제 → total=received (estimated_size 무시).
    # 중간 polling 은 estimated_size 사용. 끝 - 1 까지는 estimated.
    *mid_calls, last_call = progress_calls
    for r, t in mid_calls:
        assert t == 3072, f"중간 polling 은 estimated_size 사용: {(r, t)}"
        assert r >= 0
    last_r, last_t = last_call
    assert last_t == last_r, (
        f"완료 시 progress 는 received == total (100% 강제): {last_call}"
    )


def test_download_finished_signal_forces_progress_to_100_percent(qtbot, monkeypatch, tmp_path):
    """estimated_size 가 실제보다 클 때 (예: 8.5GB 추정 / 5.1GB 실측) — 완료 시점에
    bar 가 60% 같은 어중간한 값에서 멈춘 채로 끝나 보이는 회귀 방지.

    Fix: _on_worker_done 에서 cache 측정값을 total 로도 사용 → pct = 100%.
    """
    import sys
    cache_dir = tmp_path / "models--Qwen--Qwen3-VL-4B-Instruct"
    cache_dir.mkdir()

    def _download(**kwargs):
        # 5.1GB 분량 (실측) — estimated 8.5GB 의 60%.
        (cache_dir / "model.safetensors").write_bytes(b"x" * 5100)
        return str(cache_dir)

    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(side_effect=_download)
    fake_constants = MagicMock()
    fake_constants.HF_HUB_CACHE = str(tmp_path)
    fake_hub.constants = fake_constants
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", fake_constants)

    from screen_recorder.agent.models.downloader import ModelDownloadJob

    job = ModelDownloadJob(
        repo_id="Qwen/Qwen3-VL-4B-Instruct",
        estimated_size_bytes=8500,  # 추정 (잘못)
        poll_interval_ms=10,
    )
    progress_calls = []
    job.download_progress.connect(lambda r, t: progress_calls.append((r, t)))

    with qtbot.waitSignal(job.finished, timeout=3000):
        job.start()

    # 가장 마지막 emit 의 received == total → 100%.
    assert len(progress_calls) >= 1
    final_received, final_total = progress_calls[-1]
    assert final_received == final_total, (
        f"완료 시 bar 가 100% 안 됨: received={final_received} total={final_total} "
        f"→ pct={final_received * 100 // final_total if final_total else 0}%"
    )
    assert final_received >= 5100, "완료 progress 가 실제 cache 크기 반영해야"
