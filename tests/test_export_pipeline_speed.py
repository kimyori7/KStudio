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


def test_speed_with_trimmed_segment_does_not_misfire_partial_overlap():
    """video_track 의 segment 가 src_in 으로 잘려 source ms ≠ combined ms 인 케이스.

    회귀: _speed_overlapping_segment 가 seg.source_start_ms (원본 영상 ms) 와
    effect.in_ms (combined ms) 를 비교해 false partial overlap 발생.
    예: src 30s ~ 177s (combined 0~147s), speed 5.2s ~ 180s (combined) →
    effect.in_ms=5216 < seg.source_start=30000 으로 잘못 분류돼 export 차단.
    fix: combined_*_ms 기준 비교.
    """
    from screen_recorder.effects.segment import VideoSegment
    seg = VideoSegment(
        src="A.mp4", src_in_ms=30000, src_out_ms=177333, src_duration_ms=200000,
        media_kind="video", start_ms=0,
    )
    # 단일 segment 도 src_in>0 이라 같은 경로. video_track 1 개라도 활용.
    seg2 = VideoSegment(
        src="A.mp4", src_in_ms=0, src_out_ms=10000, src_duration_ms=200000,
        media_kind="video", start_ms=147333,
    )
    speed = SpeedEffect(in_ms=5216, out_ms=180015, rate=2.0)
    sc = Sidecar(source_path="A.mp4", source_hash="h",
                 video_track=[seg, seg2], effects=[speed])
    # 통과 — partial overlap raise 안 함.
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=200000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # speed sub-segment 가 정상 생성됐는지 — setpts=PTS/2 등장.
    assert "setpts=PTS/2" in fc


def test_speed_partial_overlap_auto_splits_segment():
    """SpeedEffect 가 segment 를 부분만 덮으면 segment 를 효과 경계에서 자동 split.

    cut 0 개 + main_duration=10000 → 원래는 main 1개([0, 10000]).
    Speed [2000, 5000] 적용 시: → 3개 sub-segment ([0,2000], [2000,5000], [5000,10000]).
    중간 sub-segment 에만 setpts=PTS/2 + atempo 가 붙는다.

    이전엔 NotImplementedError 로 export 자체가 막혔던 케이스 — 자동 split 으로 해결.
    """
    eff = SpeedEffect(in_ms=2000, out_ms=5000, rate=2.0)
    sc = Sidecar(effects=[eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    # filter_complex 안에 3개 main segment 라벨 (s0/s1/s2) 와 1개에만 setpts=PTS/2.
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    assert "trim=0.0:2.0" in fc, "head sub-segment missing"
    assert "trim=2.0:5.0" in fc, "speed sub-segment missing"
    assert "trim=5.0:10.0" in fc, "tail sub-segment missing"
    # speed 가 적용된 sub-segment 는 [trim=2.0:5.0,setpts=PTS-STARTPTS,setpts=PTS/2] 식.
    assert "setpts=PTS/2" in fc
    # head / tail 에는 setpts=PTS/2 가 직접 붙으면 안 됨 (단 한 번만 등장).
    assert fc.count("setpts=PTS/2") == 1


def test_speed_fully_contained_no_split():
    """Speed 가 segment 를 완전히 덮으면 split 불필요 — 단일 segment 그대로."""
    eff = SpeedEffect(in_ms=0, out_ms=10_000, rate=2.0)
    sc = Sidecar(effects=[eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    assert "trim=0.0:10.0" in fc
    # split 이 일어났다면 다른 trim 구간이 생겼을 것 — 없음 확인.
    assert "trim=2.0" not in fc and "trim=5.0" not in fc


def test_speed_outside_segment_no_split():
    """Speed 시간창이 main_duration 밖이면 split 도 안 생기고 효과도 적용 안 됨."""
    eff = SpeedEffect(in_ms=15_000, out_ms=20_000, rate=2.0)   # 영상 끝(10000) 밖
    sc = Sidecar(effects=[eff])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # 원본 1 segment 그대로, speed 적용 안 됨.
    assert "trim=0.0:10.0" in fc
    assert "setpts=PTS/" not in fc


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


def _stub_caption_png(monkeypatch):
    """render_caption_png 가 Qt 렌더링을 시도하지 않도록 빈 파일 생성으로 stub.

    실 테스트에서 PNG 픽셀은 검사하지 않고 argv 의 -filter_complex 만 검증.
    """
    from screen_recorder.encode import export_pipeline as ep
    def stub(c, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
    monkeypatch.setattr(ep, "render_caption_png", stub)


def test_caption_enable_uses_output_time_under_speed(tmp_path, monkeypatch):
    """배속 2.0 안의 캡션 — overlay enable 의 in/out 이 output 시간 (user/rate) 이어야.

    회귀: 이전엔 cap.in_ms/1000 그대로 enable 에 들어가 배속 segment 안 캡션이 잘못된
    위치에 표시되거나 안 보였음.

    user time: 0~10000ms 전체에 speed=2.0 → output time: 0~5000ms.
    caption user 2000~4000 → output 1000~2000.
    """
    _stub_caption_png(monkeypatch)
    from screen_recorder.effects.types.caption import CaptionEffect, Position
    sp = SpeedEffect(in_ms=0, out_ms=10000, rate=2.0)
    cap = CaptionEffect(in_ms=2000, out_ms=4000, text="hello",
                         position=Position(anchor="bottom-center"))
    sc = Sidecar(effects=[sp, cap])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path=str(tmp_path / "out.mp4"),
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg", png_dir=tmp_path,
    )
    fc = _fc_of(argv)
    # overlay enable 의 in/out 은 1.0, 2.0 (= 2000/2000, 4000/2000) 이어야 함.
    assert "between(t\\,1.0\\,2.0)" in fc, (
        f"caption overlay enable should be output time (1.0~2.0 for user 2~4s under speed=2), got fc: {fc}"
    )


def test_caption_enable_unchanged_without_speed(tmp_path, monkeypatch):
    """speed 없으면 user time 이 그대로 output time — caption enable 이 cap.in/out 그대로."""
    _stub_caption_png(monkeypatch)
    from screen_recorder.effects.types.caption import CaptionEffect, Position
    cap = CaptionEffect(in_ms=2000, out_ms=4000, text="hello",
                         position=Position(anchor="bottom-center"))
    sc = Sidecar(effects=[cap])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path=str(tmp_path / "out.mp4"),
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg", png_dir=tmp_path,
    )
    fc = _fc_of(argv)
    assert "between(t\\,2.0\\,4.0)" in fc, f"caption enable should be 2.0~4.0, got: {fc}"


def test_caption_after_speed_segment_shifts_earlier(tmp_path, monkeypatch):
    """배속 segment 뒤에 있는 캡션 — output 시간으로 앞당겨져야.

    user time 0~5000 normal, 5000~10000 speed=2.0 → output 0~5000 + 2500 = 0~7500.
    caption user 8000~9000 (배속 안) → output 5000 + (8000-5000)/2 ~ 5000 + (9000-5000)/2
                                       = 6500 ~ 7000.
    """
    _stub_caption_png(monkeypatch)
    from screen_recorder.effects.types.caption import CaptionEffect, Position
    sp = SpeedEffect(in_ms=5000, out_ms=10000, rate=2.0)
    cap = CaptionEffect(in_ms=8000, out_ms=9000, text="hi",
                         position=Position(anchor="bottom-center"))
    sc = Sidecar(effects=[sp, cap])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path=str(tmp_path / "out.mp4"),
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg", png_dir=tmp_path,
    )
    fc = _fc_of(argv)
    assert "between(t\\,6.5\\,7.0)" in fc, f"caption after speed window should map to 6.5~7.0 in output time, got: {fc}"
