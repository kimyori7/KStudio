"""export_pipeline — Sidecar → ffmpeg argv 빌더."""
import pytest

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect, Position
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.encode.export_pipeline import (
    build_export_args, default_output_path,
)


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


def test_multi_segment_track_different_srcs_raises():
    """서로 다른 src 의 segment — v2. 명시적 거부."""
    from screen_recorder.effects.segment import VideoSegment
    seg1 = VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=10000,
                         media_kind="video", start_ms=0)
    seg2 = VideoSegment(src="B.mp4", src_in_ms=0, src_out_ms=2000, src_duration_ms=5000,
                         media_kind="video", start_ms=3000)
    sc = Sidecar(source_path="A.mp4", source_hash="h", video_track=[seg1, seg2])
    with pytest.raises(NotImplementedError, match="다중 src"):
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
