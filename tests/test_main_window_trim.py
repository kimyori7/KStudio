"""MainWindow 트림 lifecycle 검증."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow


@pytest.fixture
def ffmpeg_or_skip():
    from screen_recorder.core.ffmpeg_check import find_ffmpeg
    p = find_ffmpeg()
    if not p:
        pytest.skip("ffmpeg required")
    p = Path(p).resolve()
    if not p.exists():
        pytest.skip(f"ffmpeg not at: {p}")
    return p


def _make_mp4(tmp_path, ffmpeg, name="src.mp4"):
    out = tmp_path / name
    subprocess.run(
        [str(ffmpeg), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "2", str(out)],
        check=True,
    )
    return out


@pytest.fixture
def main_window(qtbot, tmp_path, ffmpeg_or_skip):
    s = AppSettings()
    s.general.output_dir = str(tmp_path)
    s.screenshot.save_dir = str(tmp_path)
    win = MainWindow(s, ffmpeg_or_skip)
    qtbot.addWidget(win)
    return win


def test_on_trim_requested_starts_job(main_window, tmp_path, ffmpeg_or_skip):
    src = _make_mp4(tmp_path, ffmpeg_or_skip)
    with patch("screen_recorder.ui.main_window.TrimJob") as Job:
        instance = MagicMock()
        Job.return_value = instance
        main_window._on_trim_requested(src, 0, 1_000)
        Job.assert_called_once()
        instance.start.assert_called_once()
        kwargs = Job.call_args.kwargs
        assert kwargs["src"] == src
        assert kwargs["dst"].name.startswith(src.stem + "_cut_001")
        assert kwargs["in_ms"] == 0 and kwargs["out_ms"] == 1_000


def test_on_trim_requested_rejects_concurrent(main_window, tmp_path, ffmpeg_or_skip):
    src = _make_mp4(tmp_path, ffmpeg_or_skip)
    with patch("screen_recorder.ui.main_window.TrimJob") as Job:
        Job.return_value = MagicMock()
        main_window._on_trim_requested(src, 0, 1_000)
        # 두 번째 요청 — Job 은 한 번만 생성되어야
        main_window._on_trim_requested(src, 0, 1_000)
        assert Job.call_count == 1


def test_on_trim_finished_adds_library_entry_and_tab(main_window, tmp_path, ffmpeg_or_skip):
    src = _make_mp4(tmp_path, ffmpeg_or_skip)
    out = tmp_path / "src_cut_001.mp4"
    out.write_bytes(b"fake")
    initial_count = len(main_window.library_model.entries())
    main_window._active_trim_job = MagicMock()
    main_window._active_trim_src_path = src
    main_window._on_trim_finished(out)
    new_count = len(main_window.library_model.entries())
    assert new_count == initial_count + 1
    # 새 탭 추가 후 currentIndex >= 0
    assert main_window.tab_area.count() >= 1


def test_on_trim_error_cleans_up(main_window, tmp_path):
    out = tmp_path / "partial.mp4"
    out.write_bytes(b"partial")
    main_window._active_trim_job = MagicMock()
    main_window._active_trim_dst_path = out
    main_window._active_trim_src_widget = None
    main_window._on_trim_error("ffmpeg fail")
    assert not out.exists()
    assert main_window._active_trim_job is None
