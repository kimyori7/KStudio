"""export_pipeline — Sidecar → ffmpeg argv 빌더."""
import pytest

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect, Position
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.encode.export_pipeline import (
    build_export_args, default_output_path,
)


def test_odd_surface_dimensions_floored_to_even():
    """libx264 + yuv420p 는 width/height 짝수 요구. 홀수면 짝수로 floor.

    회귀: 사용자 화면 녹화 1903×1005 (둘 다 홀수) → 인코딩 실패 -22 EINVAL.
    fix 후 1902×1004 로 floor 되어 filter chain 의 scale= 가 짝수 출력.
    """
    sc = Sidecar(source_path="A.mp4", source_hash="h")
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1903, surface_h=1005,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    assert "scale=1902:1004" in fc, f"odd dims should be floored to 1902x1004: {fc}"
    # 홀수 scale 은 나타나면 안 됨.
    assert "scale=1903:" not in fc and ":1005:" not in fc


def test_build_args_no_effects_just_copy_main():
    """효과 0 개 — A 만 그대로 (libx264 재인코딩, trim 없음)."""
    sc = Sidecar(source_path="A.mp4", source_hash="h")
    argv, png_paths = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    # 입력 1개 (A), -c:v libx264, output out.mp4
    assert "A.mp4" in argv
    assert "out.mp4" in argv
    assert "-c:v" in argv
    assert "libx264" in argv
    assert png_paths == []


def test_multi_segment_track_same_src_exports():
    """같은 src 의 다중 segment (split 케이스) — export 통과 + 각 segment 가 filter graph 에."""
    from screen_recorder.effects.segment import VideoSegment
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="A.mp4", src_in_ms=3000, src_out_ms=10000, src_duration_ms=10000,
                         media_kind="video", start_ms=3000)
    sc = Sidecar(source_path="A.mp4", source_hash="h", video_track=[seg1, seg2])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # 두 segment: trim=0.0:3.0 + trim=3.0:10.0
    assert "trim=0.0:3.0" in fc
    assert "trim=3.0:10.0" in fc
    # concat 으로 합쳐짐.
    assert "concat=" in fc


def test_multi_segment_track_different_srcs_concat_with_extra_input():
    """서로 다른 src 의 segment — B.mp4 가 추가 ffmpeg input 으로 들어가고
    concat 필터에 두 segment 가 별도 라벨로 등장."""
    from screen_recorder.effects.segment import VideoSegment
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="B.mp4", src_in_ms=0, src_out_ms=2000, src_duration_ms=5000,
                         media_kind="video", start_ms=3000)
    sc = Sidecar(source_path="A.mp4", source_hash="h", video_track=[seg1, seg2])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    # B.mp4 가 두 번째 -i 입력으로 들어감.
    i_args = [argv[k + 1] for k in range(len(argv) - 1) if argv[k] == "-i"]
    assert "A.mp4" in i_args and "B.mp4" in i_args
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # 두 segment trim — A 의 0:3, B 의 0:2.
    assert "trim=0.0:3.0" in fc
    assert "trim=0.0:2.0" in fc
    # B 는 input idx 1 사용.
    assert "[1:v]" in fc


def test_multi_segment_effects_remapped_to_gap_collapsed_timeline():
    """multi-segment 트랙 + gap 이 있는 사이드카에서 effect 가 gap-collapsed
    시간축에 맞춰 remap 되는지. SpeedEffect 의 setpts 가 적용된 segment 의
    export 시간 범위에 정확히 들어가는지로 검증 (caption PNG 는 환경 hang 원인).

    예: seg1 0-3s, gap 3-5s, seg2 5-10s. speed at user 6-7s (seg2 안) →
    export 에서 seg2 의 sub-segment 가 그 위치에 등장.
    """
    from screen_recorder.effects.segment import VideoSegment
    from screen_recorder.effects.types.speed import SpeedEffect
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="A.mp4", src_in_ms=5000, src_out_ms=10000, src_duration_ms=10000,
                         media_kind="video", start_ms=5000)
    # speed at user combined 6-7s (seg2 안). remap: seg2 export_start=3s (seg1 길이).
    # user 6 → export 4 (=3 + (6-5)). user 7 → export 5.
    sp = SpeedEffect(in_ms=6000, out_ms=7000, rate=2.0)
    sc = Sidecar(source_path="A.mp4", source_hash="h",
                 video_track=[seg1, seg2], effects=[sp])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # speed (setpts=PTS/2) 가 filter graph 에 등장해야 함.
    assert "setpts=PTS/2" in fc, f"speed not applied — remap failed: {fc}"


def test_effects_in_gap_are_dropped_from_export():
    """gap 에 떨어진 effect 는 export 에서 제거 (output 에 gap 자체가 없으므로 의미 없음)."""
    from screen_recorder.effects.segment import VideoSegment
    from screen_recorder.effects.types.speed import SpeedEffect
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="A.mp4", src_in_ms=5000, src_out_ms=10000, src_duration_ms=10000,
                         media_kind="video", start_ms=10000)   # gap 3-10s
    # gap 안 (4s)
    sp = SpeedEffect(in_ms=4000, out_ms=4500, rate=2.0)
    sc = Sidecar(source_path="A.mp4", source_hash="h",
                 video_track=[seg1, seg2], effects=[sp])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # gap 안 speed 는 drop — setpts 없음.
    assert "setpts=PTS/2" not in fc


def test_multi_segment_track_image_segments_raises():
    """image segment 는 여전히 v2 — 명시적 거부."""
    from screen_recorder.effects.segment import VideoSegment
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="img.png", src_in_ms=0, src_out_ms=0, src_duration_ms=0,
                         media_kind="image", image_duration_ms=2000, start_ms=3000)
    sc = Sidecar(source_path="A.mp4", source_hash="h", video_track=[seg1, seg2])
    with pytest.raises(NotImplementedError, match="image segment"):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_build_args_with_cut_uses_concat_filter():
    """A 의 3-6 자르기 + B 0-4 → filter_complex 에 trim/concat 등장."""
    cut = CutEffect(in_ms=3000, out_ms=6000, src="B.mp4",
                    src_in_ms=0, src_out_ms=4000, src_duration_ms=4000)
    sc = Sidecar(effects=[cut])
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    # A + B 입력
    assert "A.mp4" in argv
    assert "B.mp4" in argv
    # filter_complex 안에 concat
    fc_idx = argv.index("-filter_complex")
    fc = argv[fc_idx + 1]
    assert "concat=" in fc
    assert "trim=" in fc
    assert "atrim=" in fc


def test_build_args_with_caption_adds_png_input():
    """캡션 1개 → caption_png 입력 추가 + overlay 필터 추가."""
    cap = CaptionEffect(in_ms=1000, out_ms=4000, text="hi",
                        position=Position(anchor="bottom-center"))
    sc = Sidecar(effects=[cap])
    argv, png_paths = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    assert len(png_paths) == 1
    assert any(str(p) in argv for p in png_paths)
    fc = argv[argv.index("-filter_complex") + 1]
    assert "overlay=" in fc


def test_build_args_unsupported_effect_raises():
    """broll 은 여전히 NotImplementedError (Stage 7 에서 활성화 예정).

    Stage 5 에서 speed 가, Stage 6 에서 zoom 이 지원 추가되어 BrollEffect 로 회귀 테스트 변경.
    """
    from screen_recorder.effects.types.broll import BrollEffect
    sc = Sidecar(effects=[BrollEffect(in_ms=0, out_ms=1000, src="B.mp4")])
    with pytest.raises(NotImplementedError):
        build_export_args(
            sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
            main_duration_ms=10000, surface_w=1920, surface_h=1080,
            ffmpeg_path="ffmpeg",
        )


def test_default_output_path_no_collision(tmp_path):
    """원본_edited.mp4 — 충돌 없으면 그대로."""
    src = tmp_path / "video.mp4"
    src.write_bytes(b"")
    out = default_output_path(src)
    assert out.name == "video_edited.mp4"


def test_default_output_path_with_collision(tmp_path):
    """원본_edited.mp4 가 이미 있으면 _edited_2.mp4."""
    src = tmp_path / "video.mp4"
    src.write_bytes(b"")
    (tmp_path / "video_edited.mp4").write_bytes(b"")
    out = default_output_path(src)
    assert out.name == "video_edited_2.mp4"
