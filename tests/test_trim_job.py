"""TrimJob — ffmpeg 트림 잡 단위/통합 테스트."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from screen_recorder.encode.trim import (
    TrimJob, build_video_args, build_gif_args, parse_progress_ms,
)


def test_build_video_args_mp4():
    args = build_video_args(
        ffmpeg=Path("ffmpeg"),
        src=Path("in.mp4"),
        dst=Path("out.mp4"),
        in_ms=1_000,
        out_ms=4_000,
    )
    assert args[0] == str(Path("ffmpeg"))
    assert "-ss" in args
    assert "-to" in args
    assert "-c:v" in args
    assert args[args.index("-c:v") + 1] == "libx264"
    assert "-crf" in args
    assert args[args.index("-crf") + 1] == "18"
    assert "-c:a" in args
    assert args[args.index("-c:a") + 1] == "aac"
    assert args[args.index("-ss") + 1] == "1.000"
    assert args[args.index("-to") + 1] == "4.000"
    assert "-i" in args
    assert args[args.index("-i") + 1] == str(Path("in.mp4"))
    assert args[-1] == str(Path("out.mp4"))


def test_build_gif_args_returns_two_passes(tmp_path):
    palette = tmp_path / "palette.png"
    pass1, pass2 = build_gif_args(
        ffmpeg=Path("ffmpeg"),
        src=tmp_path / "in.gif",
        dst=tmp_path / "out.gif",
        in_ms=500,
        out_ms=2_500,
        palette_path=palette,
    )
    assert "palettegen" in " ".join(pass1)
    assert "paletteuse" in " ".join(pass2)
    assert pass1[-1] == str(palette)
    assert str(palette) in pass2


def test_parse_progress_ms_returns_none_for_irrelevant_line():
    assert parse_progress_ms("frame=42 fps=10 q=28.0") is None
    assert parse_progress_ms("") is None


def test_parse_progress_ms_extracts_time():
    assert parse_progress_ms("frame=10 fps=10 time=00:00:01.50 bitrate=...") == 1500
    assert parse_progress_ms("time=00:01:23.45") == 83_450


# ---------- 통합 테스트 — 실제 ffmpeg 사용. KStudio 의 find_ffmpeg() 으로 polyfill. ----------

@pytest.fixture
def ffmpeg_or_skip():
    """KStudio 의 find_ffmpeg() 으로 ffmpeg 찾기. 없으면 통합 테스트 스킵."""
    from screen_recorder.core.ffmpeg_check import find_ffmpeg
    p = find_ffmpeg()
    if not p:
        pytest.skip("ffmpeg not available")
    # find_ffmpeg() 가 상대경로(bin/ffmpeg.exe)를 줄 수도 있으니 절대화.
    p = Path(p).resolve()
    if not p.exists():
        pytest.skip(f"ffmpeg path does not exist: {p}")
    return p


@pytest.fixture
def fixture_mp4(tmp_path, ffmpeg_or_skip):
    out = tmp_path / "fixture.mp4"
    subprocess.run(
        [str(ffmpeg_or_skip), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=320x240:d=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "5", str(out)],
        check=True,
    )
    return out


@pytest.fixture
def fixture_gif(tmp_path, ffmpeg_or_skip):
    """단색 GIF 는 palettegen 이 빈 결과를 낼 수 있어 testsrc 로 시각 변화 부여."""
    out = tmp_path / "fixture.gif"
    subprocess.run(
        [str(ffmpeg_or_skip), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=15:duration=3",
         str(out)],
        check=True,
    )
    return out


def _ffprobe_duration_ms(ffmpeg: Path, path: Path) -> int:
    proc = subprocess.run(
        [str(ffmpeg), "-i", str(path)],
        capture_output=True,
    )
    text = proc.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})", text)
    assert m, f"duration not found in: {text[:200]}"
    h, mn, s, cs = m.groups()
    return ((int(h) * 60 + int(mn)) * 60 + int(s)) * 1000 + int(cs) * 10


@pytest.mark.timeout(30)
def test_trim_mp4_produces_correct_duration(fixture_mp4, tmp_path, qtbot, ffmpeg_or_skip):
    """5초 mp4 → 1.0~3.0 초 트림 시 결과 길이가 ~2초 (±200ms)."""
    out = tmp_path / "trimmed.mp4"
    job = TrimJob(
        ffmpeg_path=ffmpeg_or_skip,
        src=fixture_mp4, dst=out,
        in_ms=1_000, out_ms=3_000,
    )
    with qtbot.waitSignal(job.finished, timeout=20_000):
        job.start()
    assert out.exists()
    dur = _ffprobe_duration_ms(ffmpeg_or_skip, out)
    assert abs(dur - 2_000) <= 200, f"duration {dur} ms not in 1800..2200"


@pytest.mark.timeout(30)
def test_trim_gif_produces_palette_2pass(fixture_gif, tmp_path, qtbot, ffmpeg_or_skip):
    """GIF 트림이 정상 완료되고 결과 파일이 생성됨."""
    out = tmp_path / "trimmed.gif"
    job = TrimJob(
        ffmpeg_path=ffmpeg_or_skip,
        src=fixture_gif, dst=out,
        in_ms=500, out_ms=2_000,
    )
    with qtbot.waitSignal(job.finished, timeout=20_000):
        job.start()
    assert out.exists() and out.stat().st_size > 0
    assert not (tmp_path / "trimmed.palette.png").exists()


def test_trim_emits_error_on_missing_input(tmp_path, qtbot, ffmpeg_or_skip):
    """존재하지 않는 입력 → error 시그널, 출력 없음."""
    job = TrimJob(
        ffmpeg_path=ffmpeg_or_skip,
        src=tmp_path / "nope.mp4",
        dst=tmp_path / "out.mp4",
        in_ms=0, out_ms=1_000,
    )
    with qtbot.waitSignal(job.error, timeout=10_000):
        job.start()
    assert not (tmp_path / "out.mp4").exists()
