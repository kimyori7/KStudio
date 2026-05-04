"""FilmstripJob 단위/통합 테스트."""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from screen_recorder.encode.filmstrip import (
    FilmstripJob, build_args, _adaptive_count,
)


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _ffmpeg() -> Path | None:
    p = shutil.which("ffmpeg")
    return Path(p) if p else None


# ---------------- 단위 ----------------

def test_build_args_uses_fps_count_over_duration():
    args = build_args(
        ffmpeg=Path("ffmpeg"),
        src=Path("in.mp4"),
        out_pattern=Path("out_%04d.png"),
        count=20,
        duration_ms=5000,
        thumb_width=64,
    )
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("fps=4."), vf  # 20/5 = 4.0
    assert "scale=64:-1" in vf
    assert args[args.index("-frames:v") + 1] == "20"


def test_adaptive_count_reduces_for_short_video():
    # 1초 영상 → 1000ms / 200ms = 5 cap, default=20 → min=5
    assert _adaptive_count(1000, 20) == 5
    # 4초 영상 → 4000/200 = 20 cap, default=20 → 20
    assert _adaptive_count(4000, 20) == 20
    # 200ms 영상 → 1 cap, 최소 2 보장
    assert _adaptive_count(200, 20) == 2


# ---------------- 통합 (ffmpeg 필요) ----------------

@pytest.fixture
def short_mp4(tmp_path: Path) -> Path:
    """5초 testsrc 영상 fixture."""
    ff = _ffmpeg()
    if ff is None:
        pytest.skip("ffmpeg PATH 에 없음")
    out = tmp_path / "src.mp4"
    subprocess.run(
        [str(ff), "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    return out


def test_filmstrip_extracts_n_images(qtbot, short_mp4: Path):
    job = FilmstripJob(
        ffmpeg_path=_ffmpeg(),
        src=short_mp4,
        duration_ms=5000,
        count=10,
        thumb_width=64,
    )
    received: list = []
    errors: list = []
    job.finished.connect(lambda imgs: received.append(imgs))
    job.error.connect(lambda msg: errors.append(msg))
    job.start()
    qtbot.waitUntil(lambda: bool(received) or bool(errors), timeout=15000)
    assert not errors, errors
    assert len(received) == 1
    images = received[0]
    assert 8 <= len(images) <= 10  # ffmpeg 가 살짝 부족하게 줄 수 있어 ±2 허용
    assert all(not img.isNull() for img in images)
    assert all(img.width() == 64 for img in images)
