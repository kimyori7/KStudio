"""export_job — TrimJob 패턴 답습. 실제 ffmpeg 실행은 안 하고 인스턴스화/취소만 검증."""
from pathlib import Path

from screen_recorder.encode.export_job import ExportJob


def test_export_job_constructs_and_can_cancel():
    job = ExportJob(
        ffmpeg_path=Path("ffmpeg"),
        argv=["ffmpeg", "-y", "input"],
        png_paths=[],
        dst_path=Path("out.mp4"),
        total_duration_ms=10000,
    )
    job.cancel()
    assert job._cancelled is True


def test_export_job_signals_defined():
    """progress / finished / error 시그널이 노출되는지."""
    job = ExportJob(
        ffmpeg_path=Path("ffmpeg"),
        argv=["ffmpeg"],
        png_paths=[],
        dst_path=Path("out.mp4"),
        total_duration_ms=10000,
    )
    assert hasattr(job, "progress")
    assert hasattr(job, "finished")
    assert hasattr(job, "error")
