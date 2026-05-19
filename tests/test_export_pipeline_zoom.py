"""export_pipeline — ZoomEffect 가 crop+scale 로 ffmpeg argv 에 들어가는지."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint


@pytest.fixture(autouse=True)
def _autostub_qt_render(monkeypatch):
    """Qt 렌더 hang 회피 — caption/speed_hud/arrow PNG stub."""
    from screen_recorder.encode import export_pipeline as ep
    def stub_cap(c, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
    def stub_hud(eff, *, font_pt, dst):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
        return (200, 40)
    def stub_arrow(a, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
    monkeypatch.setattr(ep, "render_caption_png", stub_cap)
    monkeypatch.setattr(ep, "render_speed_hud_png", stub_hud)
    monkeypatch.setattr(ep, "render_arrow_png", stub_arrow)
from screen_recorder.encode.export_pipeline import (
    _zoom_crop_scale_filter, build_export_args,
)


def _build_argv_with_zoom(zoom_eff: ZoomEffect, *, main_duration_ms=10000,
                            surface_w=1920, surface_h=1080) -> list[str]:
    sc = Sidecar(effects=[zoom_eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=main_duration_ms, surface_w=surface_w, surface_h=surface_h,
        ffmpeg_path="ffmpeg",
    )
    return argv


def _fc_of(argv: list[str]) -> str:
    return argv[argv.index("-filter_complex") + 1]


# ---- 기본 ----
def test_no_zoom_unchanged():
    """zoom 0 개 — argv 에 crop= 가 등장하지 않아야 함."""
    sc = Sidecar()
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = _fc_of(argv)
    assert "crop=" not in fc


def test_zoom_2x_applies_crop_scale():
    """전 구간 2.0× 줌 (cx=0.5, cy=0.5) → crop=960:540:480:270,scale=1920:1080 등장."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10000, start=pt, end=pt)
    argv = _build_argv_with_zoom(eff)
    fc = _fc_of(argv)
    # surface 1920x1080, scale=2.0 → crop=960:540:480:270 (중앙 정렬)
    assert "crop=960:540:480:270" in fc
    # scale=1920:1080 가 두 번 등장 (기본 stretch + zoom 후 복귀) — 줌 후 scale 만 검증.
    assert "scale=1920:1080" in fc


def test_zoom_offcenter_applies_correct_crop_offset():
    """cx=0.25, cy=0.75, scale=2.0 — crop x 가 오프센터 값으로 계산."""
    pt = ZoomPoint(cx=0.25, cy=0.75, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10000, start=pt, end=pt)
    argv = _build_argv_with_zoom(eff)
    fc = _fc_of(argv)
    # cx=0.25*1920=480, crop_w=960 → crop_x = 480-480 = 0
    # cy=0.75*1080=810, crop_h=540 → crop_y = 810-270 = 540
    assert "crop=960:540:0:540" in fc


def test_zoom_plus_cut_raises():
    """zoom + range cut 동시 → NotImplementedError (v2 follow-up)."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    zoom = ZoomEffect(in_ms=0, out_ms=5000, start=pt, end=pt)
    cut = CutEffect(in_ms=6000, out_ms=8000)
    sc = Sidecar(effects=[zoom, cut])
    with pytest.raises(NotImplementedError, match="zoom.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_zoom_plus_insert_cut_raises():
    """zoom + cut(splice with insert) — insert 가 시간축을 늘리므로 v2 차단."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    zoom = ZoomEffect(in_ms=0, out_ms=5000, start=pt, end=pt)
    cut = CutEffect(in_ms=6000, out_ms=6000, src="B.mp4",
                    src_in_ms=0, src_out_ms=2000, src_duration_ms=2000)
    sc = Sidecar(effects=[zoom, cut])
    with pytest.raises(NotImplementedError, match="zoom.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_zoom_plus_speed_raises():
    """zoom + speed 동시 → NotImplementedError (v2 follow-up)."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    zoom = ZoomEffect(in_ms=0, out_ms=5000, start=pt, end=pt)
    speed = SpeedEffect(in_ms=0, out_ms=10000, rate=2.0)
    sc = Sidecar(effects=[zoom, speed])
    with pytest.raises(NotImplementedError, match="zoom.speed"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_zoom_partial_overlap_auto_splits_segment():
    """ZoomEffect 가 segment 를 부분만 덮으면 segment 를 효과 경계에서 자동 split.

    cut 0 개 + main_duration=10000 → 원래는 main 1개([0, 10000]).
    Zoom [2000, 5000] 적용 시: → 3개 sub-segment, 중간만 crop+scale 필터.
    이전엔 NotImplementedError 였던 케이스 — 자동 split 으로 해결.
    """
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=2000, out_ms=5000, start=pt, end=pt)
    sc = Sidecar(effects=[eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    assert "trim=0.0:2.0" in fc
    assert "trim=2.0:5.0" in fc
    assert "trim=5.0:10.0" in fc
    # crop 은 zoom sub-segment 에만 한 번 등장.
    assert fc.count("crop=") == 1


# ---- _zoom_crop_scale_filter unit tests ----
def test_crop_scale_centered_2x():
    """cx=0.5, cy=0.5, scale=2.0, 1920×1080 → crop=960:540:480:270,scale=...flags=lanczos."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=1000, start=pt, end=pt)
    f = _zoom_crop_scale_filter(eff, 1920, 1080)
    assert f == "crop=960:540:480:270,scale=1920:1080:flags=lanczos"


def test_crop_scale_3x():
    """cx=0.5, cy=0.5, scale=3.0, 1920×1080 → crop=640:360:640:360."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=3.0)
    eff = ZoomEffect(in_ms=0, out_ms=1000, start=pt, end=pt)
    f = _zoom_crop_scale_filter(eff, 1920, 1080)
    assert "crop=640:360:640:360" in f
    assert "scale=1920:1080" in f


def test_crop_scale_no_zoom_at_1x():
    """scale=1.0 — crop 이 영상 전체 크기 (사실상 no-op)."""
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=1.0)
    eff = ZoomEffect(in_ms=0, out_ms=1000, start=pt, end=pt)
    f = _zoom_crop_scale_filter(eff, 1920, 1080)
    assert f == "crop=1920:1080:0:0,scale=1920:1080:flags=lanczos"
