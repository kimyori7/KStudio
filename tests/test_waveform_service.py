"""WaveformJob 단위 테스트."""
import pytest


def test_waveform_job_constructs():
    from screen_recorder.services.waveform_service import WaveformJob
    job = WaveformJob(ffmpeg_path="ffmpeg", src="v.mp4",
                      buckets_per_sec=50, sample_rate=8000)
    assert job is not None
    assert hasattr(job, "finished") and hasattr(job, "error")


def test_service_cache_hit_emits_without_job(qtbot, tmp_path, monkeypatch):
    from screen_recorder.services import waveform_service as ws
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    svc = ws.WaveformService(ffmpeg_path="ffmpeg")
    # 캐시에 직접 주입 후 request → job 없이 즉시 emit.
    key = svc._cache_key(str(src))
    svc._cache[key] = [0.1, 0.2, 0.3]
    got = []
    svc.waveform_ready.connect(lambda s, p: got.append((s, p)))
    svc.request(str(src))
    assert got == [(str(src), [0.1, 0.2, 0.3])]


def test_service_no_audio_short_circuits(qtbot, tmp_path, monkeypatch):
    from screen_recorder.services import waveform_service as ws
    monkeypatch.setattr(ws, "has_audio_stream", lambda s: False)
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    svc = ws.WaveformService(ffmpeg_path="ffmpeg")
    got = []
    svc.waveform_ready.connect(lambda s, p: got.append((s, p)))
    svc.request(str(src))
    assert got == [(str(src), [])]   # 소리 없음 = 빈 peaks, job 안 띄움
