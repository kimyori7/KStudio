"""export_pipeline — BrollEffect PiP 가 ffmpeg argv 에 overlay+scale 로 들어가는지."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint
from screen_recorder.encode.export_pipeline import (
    _broll_pip_xy, build_export_args,
)


def _build_argv_with_broll(broll: BrollEffect, *, main_duration_ms=10000,
                            surface_w=1920, surface_h=1080) -> list[str]:
    sc = Sidecar(effects=[broll])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=main_duration_ms, surface_w=surface_w, surface_h=surface_h,
        ffmpeg_path="ffmpeg",
    )
    return argv


def _fc_of(argv: list[str]) -> str:
    return argv[argv.index("-filter_complex") + 1]


# ---- 기본 ----
def test_no_broll_unchanged():
    """broll 0 개 — argv 구조 변경 없음 (fc 에 overlay 가 캡션용만 있거나 없어야)."""
    sc = Sidecar()
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = _fc_of(argv)
    # broll 가이드 식별 — broll{i} 라벨이 없어야.
    assert "[broll0]" not in fc
    assert "[vb0]" not in fc


def test_pip_broll_adds_scale_overlay():
    """단일 PiP broll — argv 의 fc 에 scale=W*ratio:H*ratio + overlay=corner_x:corner_y 등장."""
    broll = BrollEffect(
        in_ms=2000, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    argv = _build_argv_with_broll(broll)
    fc = _fc_of(argv)
    # 1920×0.3=576, 1080×0.3=324 → scale=576:324
    assert "scale=576:324" in fc
    # corner=bottom-right, surface 1920×1080, margin 8 →
    #   x = 1920-576-8 = 1336, y = 1080-324-8 = 748
    assert "overlay=1336:748" in fc
    # enable='between(t,2.0,5.0)' (escape \, 포함)
    assert "between(t\\,2.0\\,5.0)" in fc
    # broll 입력 -i b.mp4 추가
    assert "-i" in argv and "b.mp4" in argv


def test_pip_broll_top_left_corner():
    """top-left 모서리 — overlay=8:8."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="top-left", size_ratio=0.4),
        audio_mix="original_only",
    )
    argv = _build_argv_with_broll(broll)
    fc = _fc_of(argv)
    # 1920×0.4=768, 1080×0.4=432
    assert "scale=768:432" in fc
    assert "overlay=8:8" in fc


def test_pip_broll_top_right_corner():
    """top-right — x=W-pip_w-8."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="top-right", size_ratio=0.2),
        audio_mix="original_only",
    )
    argv = _build_argv_with_broll(broll)
    fc = _fc_of(argv)
    # 1920×0.2=384, 1080×0.2=216
    # top-right: x=1920-384-8=1528, y=8
    assert "overlay=1528:8" in fc


def test_pip_broll_bottom_left_corner():
    """bottom-left — x=8, y=H-pip_h-8."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-left", size_ratio=0.3),
        audio_mix="original_only",
    )
    argv = _build_argv_with_broll(broll)
    fc = _fc_of(argv)
    # 1920×0.3=576, 1080×0.3=324; y=1080-324-8=748
    assert "overlay=8:748" in fc


# ---- v2 차단 ----
def test_fullscreen_broll_raises():
    """placement='fullscreen' → NotImplementedError."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="fullscreen", pip=None,
        audio_mix="original_only",
    )
    sc = Sidecar(effects=[broll])
    with pytest.raises(NotImplementedError, match="fullscreen broll"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_broll_plus_speed_raises():
    """broll + speed 동시 → NotImplementedError."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    speed = SpeedEffect(in_ms=0, out_ms=10000, rate=2.0)
    sc = Sidecar(effects=[broll, speed])
    with pytest.raises(NotImplementedError, match="broll.speed"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_broll_plus_zoom_raises():
    """broll + zoom 동시 → NotImplementedError."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    zoom = ZoomEffect(in_ms=0, out_ms=10000, start=pt, end=pt)
    sc = Sidecar(effects=[broll, zoom])
    with pytest.raises(NotImplementedError, match="broll.zoom"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_broll_plus_range_cut_raises():
    """broll + range cut → NotImplementedError."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    cut = CutEffect(in_ms=6000, out_ms=8000)
    sc = Sidecar(effects=[broll, cut])
    with pytest.raises(NotImplementedError, match="broll.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_broll_plus_insert_cut_raises():
    """broll + cut(splice with insert) — insert 가 시간축을 늘리므로 v2 차단."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    cut = CutEffect(in_ms=6000, out_ms=6000, src="X.mp4",
                    src_in_ms=0, src_out_ms=2000, src_duration_ms=2000)
    sc = Sidecar(effects=[broll, cut])
    with pytest.raises(NotImplementedError, match="broll.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_broll_plus_simple_splice_passes():
    """broll + 단순 splice (in==out, no insert) 는 시간축 영향 없으니 통과해야."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="original_only",
    )
    splice = CutEffect(in_ms=3000, out_ms=3000)   # 단순 splice
    sc = Sidecar(effects=[broll, splice])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = _fc_of(argv)
    assert "[broll0]" in fc


@pytest.mark.parametrize("audio_mix", ["both", "broll_only", "mute"])
def test_broll_audio_mix_non_original_raises(audio_mix):
    """audio_mix != 'original_only' → NotImplementedError."""
    broll = BrollEffect(
        in_ms=0, out_ms=5000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix=audio_mix,
    )
    sc = Sidecar(effects=[broll])
    with pytest.raises(NotImplementedError, match="audio_mix"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


# ---- _broll_pip_xy unit tests ----
def test_pip_xy_top_left():
    assert _broll_pip_xy("top-left", 1920, 1080, 576, 324) == (8, 8)


def test_pip_xy_top_right():
    assert _broll_pip_xy("top-right", 1920, 1080, 576, 324) == (1336, 8)


def test_pip_xy_bottom_left():
    assert _broll_pip_xy("bottom-left", 1920, 1080, 576, 324) == (8, 748)


def test_pip_xy_bottom_right():
    assert _broll_pip_xy("bottom-right", 1920, 1080, 576, 324) == (1336, 748)


def test_pip_xy_unknown_corner_falls_back_to_bottom_right():
    """알 수 없는 corner → 기본 우하단."""
    assert _broll_pip_xy("invalid", 1920, 1080, 576, 324) == (1336, 748)
