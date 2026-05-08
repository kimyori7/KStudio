"""export_pipeline — SpeedEffect 가 setpts/atempo 로 ffmpeg argv 에 들어가는지."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.encode.export_pipeline import (
    _atempo_chain, build_export_args,
)


def _build_argv_with_speed(speed_eff: SpeedEffect, *, main_duration_ms=10000) -> list[str]:
    sc = Sidecar(effects=[speed_eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=main_duration_ms, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    return argv


def _fc_of(argv: list[str]) -> str:
    return argv[argv.index("-filter_complex") + 1]


def test_no_speed_unchanged():
    """speed 0 개 — argv 에 setpts=PTS/, atempo= 가 등장하지 않아야 함."""
    sc = Sidecar()
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = _fc_of(argv)
    assert "setpts=PTS/" not in fc
    assert "atempo=" not in fc


def test_speed_2x_applies_setpts_atempo():
    """전 구간 2.0× 배속 → setpts=PTS/2 + atempo=2 등장."""
    eff = SpeedEffect(in_ms=0, out_ms=10000, rate=2.0)
    argv = _build_argv_with_speed(eff)
    fc = _fc_of(argv)
    assert "setpts=PTS/2" in fc
    assert "atempo=2" in fc


def test_speed_4x_chains_atempo():
    """rate=4.0 — atempo 의 [0.5, 2.0] 한계 → atempo=2.0,atempo=2.0 체인."""
    eff = SpeedEffect(in_ms=0, out_ms=10000, rate=4.0)
    argv = _build_argv_with_speed(eff)
    fc = _fc_of(argv)
    assert "atempo=2.0,atempo=2.0" in fc
    assert "setpts=PTS/4" in fc


def test_speed_05x_uses_atempo_05():
    """rate=0.5 — 한 번의 atempo=0.5 로 표현. setpts=PTS/0.5 (= PTS*2)."""
    eff = SpeedEffect(in_ms=0, out_ms=10000, rate=0.5)
    argv = _build_argv_with_speed(eff)
    fc = _fc_of(argv)
    assert "atempo=0.5" in fc
    assert "setpts=PTS/0.5" in fc


def test_speed_plus_cut_raises():
    """speed + range cut 동시 → NotImplementedError (v2 follow-up)."""
    speed = SpeedEffect(in_ms=0, out_ms=5000, rate=2.0)
    cut = CutEffect(in_ms=6000, out_ms=8000)
    sc = Sidecar(effects=[speed, cut])
    with pytest.raises(NotImplementedError, match="speed.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_speed_plus_insert_cut_raises():
    """speed + cut(splice with insert) — insert 가 시간축을 늘리므로 v2 차단."""
    speed = SpeedEffect(in_ms=0, out_ms=5000, rate=2.0)
    cut = CutEffect(in_ms=6000, out_ms=6000, src="B.mp4",
                    src_in_ms=0, src_out_ms=2000, src_duration_ms=2000)
    sc = Sidecar(effects=[speed, cut])
    with pytest.raises(NotImplementedError, match="speed.cut"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_speed_partial_overlap_raises():
    """SpeedEffect 가 segment 를 부분적으로만 덮음 → NotImplementedError.

    cut 0 개 + main_duration=10000 → segments 는 main 1개([0, 10000]).
    Speed 가 [2000, 5000] 만 덮으면 segment 를 부분만 덮어 v1 에서 차단.
    """
    eff = SpeedEffect(in_ms=2000, out_ms=5000, rate=2.0)
    sc = Sidecar(effects=[eff])
    with pytest.raises(NotImplementedError, match="partial overlap"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


# ---- _atempo_chain unit tests ----
def test_atempo_chain_unity():
    """rate=1.0 → atempo=1.0 (정수는 항상 N.0 표기로 통일)."""
    assert _atempo_chain(1.0) == "atempo=1.0"


def test_atempo_chain_in_range():
    assert _atempo_chain(2.0) == "atempo=2.0"
    assert _atempo_chain(0.5) == "atempo=0.5"
    assert _atempo_chain(1.5) == "atempo=1.5"


def test_atempo_chain_above_2x():
    """4.0 → atempo=2.0,atempo=2.0; 3.0 → atempo=2.0,atempo=1.5."""
    assert _atempo_chain(4.0) == "atempo=2.0,atempo=2.0"
    assert _atempo_chain(3.0) == "atempo=2.0,atempo=1.5"


def test_atempo_chain_below_05x():
    """0.25 → atempo=0.5,atempo=0.5."""
    assert _atempo_chain(0.25) == "atempo=0.5,atempo=0.5"
