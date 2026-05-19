"""sidecar.trim 이 export argv 의 main segment trim filter 로 반영되는지."""
from __future__ import annotations
from pathlib import Path

import pytest

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.encode.export_pipeline import build_export_args


@pytest.fixture(autouse=True)
def _autostub_qt_render(monkeypatch):
    from screen_recorder.encode import export_pipeline as ep
    def stub_cap(c, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path as _P
        _P(dst).parent.mkdir(parents=True, exist_ok=True)
        _P(dst).write_bytes(b"")
    def stub_hud(eff, *, font_pt, dst):
        from pathlib import Path as _P
        _P(dst).parent.mkdir(parents=True, exist_ok=True)
        _P(dst).write_bytes(b"")
        return (200, 40)
    def stub_arrow(a, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path as _P
        _P(dst).parent.mkdir(parents=True, exist_ok=True)
        _P(dst).write_bytes(b"")
    monkeypatch.setattr(ep, "render_caption_png", stub_cap)
    monkeypatch.setattr(ep, "render_speed_hud_png", stub_hud)
    monkeypatch.setattr(ep, "render_arrow_png", stub_arrow)


def test_no_trim_main_segment_uses_full_range(tmp_path):
    """trim 없으면 [0:v]trim=0:5 (전체)."""
    sc = Sidecar(trim=Trim(in_ms=0, out_ms=0))
    argv, _ = build_export_args(
        sidecar=sc, src_path=Path("a.mp4"), dst_path=tmp_path / "o.mp4",
        main_duration_ms=5_000, surface_w=320, surface_h=180,
        ffmpeg_path="ffmpeg",
    )
    fc = next(s for s in argv if "trim=" in s and "[0:v]" in s)
    assert "trim=0.0:5.0" in fc


def test_trim_clips_main_segment_to_range(tmp_path):
    """trim=(1000, 4000) → [0:v]trim=1.0:4.0."""
    sc = Sidecar(trim=Trim(in_ms=1_000, out_ms=4_000))
    argv, _ = build_export_args(
        sidecar=sc, src_path=Path("a.mp4"), dst_path=tmp_path / "o.mp4",
        main_duration_ms=5_000, surface_w=320, surface_h=180,
        ffmpeg_path="ffmpeg",
    )
    fc = next(s for s in argv if "trim=" in s and "[0:v]" in s)
    assert "trim=1.0:4.0" in fc


def test_trim_with_only_out_clips_to_zero_to_out(tmp_path):
    """trim=(0, 3000) → [0:v]trim=0.0:3.0 (in 없을 때)."""
    sc = Sidecar(trim=Trim(in_ms=0, out_ms=3_000))
    argv, _ = build_export_args(
        sidecar=sc, src_path=Path("a.mp4"), dst_path=tmp_path / "o.mp4",
        main_duration_ms=5_000, surface_w=320, surface_h=180,
        ffmpeg_path="ffmpeg",
    )
    fc = next(s for s in argv if "trim=" in s and "[0:v]" in s)
    assert "trim=0.0:3.0" in fc
