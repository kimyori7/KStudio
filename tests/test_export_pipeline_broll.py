"""export_pipeline — BrollEffect PiP 가 ffmpeg argv 에 overlay+scale 로 들어가는지."""
from __future__ import annotations

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint


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


@pytest.mark.parametrize("audio_mix", ["mute", "broll_only", "both"])
def test_broll_audio_mix_non_original_builds_filter(audio_mix):
    """Phase 32 — audio_mix 모드별 filter_complex 가 생성된다 (v2 audio mixing 지원).

    각 모드는 main audio 의 broll 시간창에 volume= attenuation 을 적용.
    broll_only / both 는 추가로 broll audio stream 을 adelay + amix.
    """
    broll = BrollEffect(
        in_ms=1000, out_ms=4000, src="b.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix=audio_mix,
        audio_balance=0.5,
    )
    sc = Sidecar(effects=[broll])
    argv, _pngs = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    # filter_complex 안에 volume enable / amix 키워드 확인.
    fc_idx = argv.index("-filter_complex")
    fc = argv[fc_idx + 1]
    assert "volume=enable=" in fc, (
        f"audio_mix={audio_mix} 인데 volume gating 안 들어감: {fc}"
    )
    if audio_mix in ("broll_only", "both"):
        assert "amix=inputs=2" in fc, (
            f"audio_mix={audio_mix} 인데 amix 안 들어감: {fc}"
        )
    else:   # mute
        # mute 모드는 broll audio 추가 안 함 — amix 없음.
        assert "amix=inputs=2" not in fc, (
            f"mute 모드인데 amix 가 들어감: {fc}"
        )


def test_broll_image_src_audio_mix_falls_back_to_original_only():
    """이미지 broll (.png) 의 audio_mix 가 'broll_only' 이어도 amix 추가 안 됨 (audio 없음)."""
    broll = BrollEffect(
        in_ms=1000, out_ms=4000, src="image.png",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
        audio_mix="broll_only",
    )
    sc = Sidecar(effects=[broll])
    argv, _pngs = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc_idx = argv.index("-filter_complex")
    fc = argv[fc_idx + 1]
    # main mute (broll_only 라서) 는 적용. broll audio 는 추가 X (이미지).
    assert "volume=enable=" in fc
    assert "amix=inputs=2" not in fc


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


def test_pip_xy_pos_x_y_overrides_corner():
    """pos_x / pos_y 가 둘 다 set 이면 corner 무시 — 자유 위치."""
    # 1920x1080 surface 에서 정규화 (0.25, 0.5) → (480, 540)
    assert _broll_pip_xy(
        "top-left", 1920, 1080, 576, 324, pos_x=0.25, pos_y=0.5
    ) == (480, 540)


def test_pip_xy_partial_pos_falls_back_to_corner():
    """pos_x 만 있고 pos_y 없으면 corner 사용 (둘 다 set 일 때만 자유 위치)."""
    assert _broll_pip_xy(
        "bottom-right", 1920, 1080, 576, 324, pos_x=0.25, pos_y=None
    ) == (1336, 748)
