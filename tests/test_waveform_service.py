"""WaveformJob 단위 테스트."""
import pytest


def test_waveform_job_constructs():
    from screen_recorder.services.waveform_service import WaveformJob
    job = WaveformJob(ffmpeg_path="ffmpeg", src="v.mp4",
                      buckets_per_sec=50, sample_rate=8000)
    assert job is not None
    assert hasattr(job, "finished") and hasattr(job, "error")
