"""export_pipeline — Sidecar → ffmpeg argv 빌더."""
import pytest

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect, Position
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.encode.export_pipeline import (
    build_export_args, default_output_path,
)


@pytest.fixture(autouse=True)
def _autostub_qt_render(monkeypatch):
    """render_caption_png / render_speed_hud_png / render_arrow_png 가 Qt 호출 시
    (QApplication 없으면) hang 하는 회귀 회피. 기본 stub — argv 검증만 하는 테스트들
    이라 픽셀은 무관."""
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


def test_caption_spanning_segment_boundary_drops_seam_fade():
    """캡션이 세그먼트 경계를 넘으면 조각으로 쪼개지는데, 각 조각이 원래 fade 를 그대로
    가지면 이음매에서 fade-out+fade-in 이 겹쳐 캡션이 투명해졌다 돌아오며 **깜빡인다**
    (사용자 보고). 이음매 쪽 fade 를 0 으로 → 조각 사이 연속 표시. 진짜 바깥 가장자리
    (실제 caption in/out)만 fade 유지."""
    from screen_recorder.effects.segment import VideoSegment
    from screen_recorder.effects.types.caption import CaptionEffect, Fade
    from screen_recorder.encode.export_pipeline import _remap_effects_to_gap_collapsed
    track = [
        VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=2000, src_duration_ms=5000,
                     media_kind="video", start_ms=0),
        VideoSegment(src="A.mp4", src_in_ms=2000, src_out_ms=5000, src_duration_ms=5000,
                     media_kind="video", start_ms=2000),
    ]
    cap = CaptionEffect(in_ms=1000, out_ms=3000, text="x", fade=Fade(in_ms=300, out_ms=300))
    pieces = _remap_effects_to_gap_collapsed([cap], track)
    assert len(pieces) == 2, "경계를 넘는 캡션은 두 조각으로 쪼개진다"
    p1, p2 = sorted(pieces, key=lambda e: e.in_ms)
    # 첫 조각: 실제 시작이라 fade_in 유지, 이음매 끝이라 fade_out=0
    assert p1.fade.in_ms == 300 and p1.fade.out_ms == 0, f"p1 fade={p1.fade}"
    # 둘째 조각: 이음매 시작이라 fade_in=0, 실제 끝이라 fade_out 유지
    assert p2.fade.in_ms == 0 and p2.fade.out_ms == 300, f"p2 fade={p2.fade}"


def test_alpha_overlay_chain_omits_zero_fade():
    """fade=0 이면 fade 필터 자체를 빼야 한다 — ffmpeg fade 는 d=0 을 '기본 길이 페이드'
    로 처리해 이음매 깜빡임을 오히려 만든다."""
    from screen_recorder.encode.export_pipeline import _alpha_overlay_chain
    # 양쪽 fade 0 → format=rgba 만, fade 없음
    c0 = _alpha_overlay_chain(3, "cap0", 2.0, 5.0, 0.0, 0.0)
    assert "fade=" not in c0
    assert c0 == "[3:v]format=rgba[cap0]"
    # in 만 있음
    c1 = _alpha_overlay_chain(3, "cap0", 2.0, 5.0, 0.3, 0.0)
    assert "fade=t=in:st=2.0:d=0.3" in c1
    assert "fade=t=out" not in c1
    # out 만 있음
    c2 = _alpha_overlay_chain(3, "cap0", 2.0, 5.0, 0.0, 0.3)
    assert "fade=t=in" not in c2
    assert "fade=t=out:st=4.7:d=0.3" in c2


def test_caption_within_one_segment_keeps_both_fades():
    """한 세그먼트 안에 완전히 든 캡션은 쪼개지지 않고 양쪽 fade 그대로 (회귀 가드)."""
    from screen_recorder.effects.segment import VideoSegment
    from screen_recorder.effects.types.caption import CaptionEffect, Fade
    from screen_recorder.encode.export_pipeline import _remap_effects_to_gap_collapsed
    track = [
        VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=5000, src_duration_ms=10000,
                     media_kind="video", start_ms=0),
        VideoSegment(src="A.mp4", src_in_ms=5000, src_out_ms=10000, src_duration_ms=10000,
                     media_kind="video", start_ms=5000),
    ]
    cap = CaptionEffect(in_ms=1000, out_ms=3000, text="x", fade=Fade(in_ms=300, out_ms=300))
    pieces = _remap_effects_to_gap_collapsed([cap], track)
    assert len(pieces) == 1
    assert pieces[0].fade.in_ms == 300 and pieces[0].fade.out_ms == 300


def test_encoder_uses_nvenc_when_available(monkeypatch):
    """GPU(NVENC) 가 동작하면 -c:v h264_nvenc, 아니면 libx264 로 폴백 (사용자 요청)."""
    from screen_recorder.encode import export_pipeline as ep
    sc = Sidecar(source_path="A.mp4", source_hash="h")

    monkeypatch.setattr(ep, "nvenc_available", lambda *a, **k: True)
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080, ffmpeg_path="ffmpeg",
    )
    assert "h264_nvenc" in argv
    assert "libx264" not in argv

    monkeypatch.setattr(ep, "nvenc_available", lambda *a, **k: False)
    argv2, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=10000, surface_w=1920, surface_h=1080, ffmpeg_path="ffmpeg",
    )
    assert "libx264" in argv2
    assert "h264_nvenc" not in argv2


def test_nvenc_available_false_for_dummy_path():
    """실제 파일 아닌 더미 ffmpeg 경로면 테스트 인코드 안 하고 False (단위 테스트 결정성)."""
    from screen_recorder.encode.export_pipeline import nvenc_available
    assert nvenc_available("definitely_not_a_real_ffmpeg_xyz") is False


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
    """같은 src 의 다중 segment (split 케이스) — export 통과 + 각 segment 가 filter graph 에.

    2026-06-09 OOM fix: 첫 조각만 [0:v]trim 으로 두고, 둘째부터는 -ss/-t 독립 입력으로
    분리한다(한 디코더 fan-out → concat 버퍼링 폭주 방지). 그래서 둘째 조각은 더 이상
    [0:v]trim=3.0:10.0 으로 나타나지 않고 별도 입력 [1:v] 로 등장한다.
    """
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
    # 첫 조각은 [0:v]trim 유지 (소비자 1개 → fan-out 없음).
    assert "[0:v]trim=0.0:3.0" in fc
    # 둘째 조각의 *비디오* 는 -ss 독립 입력 → [0:v]trim=3.0:10.0 으로는 안 나타남.
    # (오디오는 전용 오디오 입력에서 atrim=3.0:10.0 — 정상.)
    assert "[0:v]trim=3.0:10.0" not in fc
    # [0:v] 소비자는 최대 1개여야 (fan-out 금지 불변식).
    assert fc.count("[0:v]") <= 1
    # 둘째 조각용 -ss 분리 입력이 있어야.
    assert "-ss" in argv
    assert "[1:v]" in fc
    # 비디오·오디오 concat 분리 (OOM fix part 2).
    assert "concat=n=2:v=1:a=0" in fc
    assert "concat=n=2:v=0:a=1" in fc


def test_multiple_main_segments_avoid_decoder_fanout():
    """2026-06-09 OOM 회귀 가드: 컷으로 main 조각이 ≥2 개면, 한 디코더([0:v])에서
    여러 trim 이 갈라지고 concat 이 순서대로 소비하는 동안 아직 안 읽힌 가지가 통째로
    버퍼링된다 → 29분 영상에서 수십 GB → '-12 Cannot allocate memory' 로 죽음(실측:
    6초만에 14GB 폭증, frame=0). 수정: 첫 조각만 [0:v]trim, 이후 조각은 -ss/-t 로
    그 지점부터 독립 디코딩하는 별도 입력으로 분리 → 어떤 입력도 trim 소비자 ≤ 1.
    """
    from screen_recorder.effects.segment import VideoSegment
    segs = [
        VideoSegment(src="A.mp4", src_in_ms=0, src_out_ms=3000, src_duration_ms=30000,
                     media_kind="video", start_ms=0),
        VideoSegment(src="A.mp4", src_in_ms=3000, src_out_ms=15000, src_duration_ms=30000,
                     media_kind="video", start_ms=3000),
        VideoSegment(src="A.mp4", src_in_ms=15000, src_out_ms=30000, src_duration_ms=30000,
                     media_kind="video", start_ms=15000),
    ]
    sc = Sidecar(source_path="A.mp4", source_hash="h", video_track=segs)
    argv, _ = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path="out.mp4",
        main_duration_ms=30000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg",
    )
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # 핵심 불변식: [0:v] 를 소비하는 trim 은 최대 1개 (fan-out 금지).
    assert fc.count("[0:v]") <= 1, f"[0:v] fan-out 발견: {fc}"
    # 추가 2 조각만큼 -ss 분리 입력이 있어야.
    assert argv.count("-ss") >= 2
    # A.mp4 가 원본 입력 + seek 입력 2개 = 최소 3번 -i.
    i_args = [argv[k + 1] for k in range(len(argv) - 1) if argv[k] == "-i"]
    assert i_args.count("A.mp4") >= 3
    # 여전히 concat 으로 합쳐짐.
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


def test_multi_segment_track_letterboxes_instead_of_stretching():
    """비율 다른 클립을 멀티트랙으로 이어붙일 때 강제 stretch(찌그러짐) 대신
    fit(레터박스: 비율 보존 + 검은 여백) 으로 캔버스에 맞춘다.

    회귀: 멀티트랙 concat 이 main 조각(line 620)과 insert 조각(line 632)을 모두
    'stretch' 로 강제해 비율 다른 클립이 찌그러졌다 (사용자 보고 2026-06-19).
    캔버스=첫 클립 기준(surface_w/h)은 그대로 유지하고, 맞춤 방식만 fit 으로 바꾼다.
    """
    from screen_recorder.effects.segment import VideoSegment
    # seg1 = src_path (source="main", line 620 경로), seg2 = 다른 src (insert, line 632 경로).
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
    fc = next(argv[i + 1] for i, a in enumerate(argv) if a == "-filter_complex")
    # 두 조각(main + insert) 모두 비율 보존 레터박스(fit) — 검은 pad 포함.
    assert fc.count("force_original_aspect_ratio=decrease") == 2, \
        f"두 클립 모두 fit(레터박스) 되어야 함: {fc}"
    # 강제 stretch (scale 뒤에 바로 format 이 붙는 모양) 는 사라져야 한다.
    assert "scale=1920:1080,format" not in fc, f"강제 stretch 가 남아있음: {fc}"


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


def test_mute_audio_drops_audio_chain(tmp_path):
    from screen_recorder.encode.export_pipeline import build_export_args
    from screen_recorder.effects.sidecar import Sidecar
    from screen_recorder.effects.segment import VideoSegment

    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")   # 존재만; has_audio_stream 은 가짜 경로에 낙관 True
    sc = Sidecar(source_path=str(src),
                 video_track=[VideoSegment(src=str(src), src_in_ms=0,
                                           src_out_ms=0, src_duration_ms=1000)])

    argv_muted, _ = build_export_args(
        sidecar=sc, src_path=str(src), dst_path=str(tmp_path / "o.mp4"),
        main_duration_ms=1000, surface_w=320, surface_h=240,
        ffmpeg_path="ffmpeg", mute_audio=True,
    )
    joined = " ".join(argv_muted)
    assert "-c:a" not in argv_muted
    assert "[0:a]" not in joined and "[conca]" not in joined

    argv_kept, _ = build_export_args(
        sidecar=sc, src_path=str(src), dst_path=str(tmp_path / "o2.mp4"),
        main_duration_ms=1000, surface_w=320, surface_h=240,
        ffmpeg_path="ffmpeg", mute_audio=False,
    )
    assert "-c:a" in argv_kept   # 음소거 안 하면 오디오 유지
