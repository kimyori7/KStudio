"""AudioExportSettings + build_audio_export_args + compute_audio_keep_intervals.

2026-05-20 새 기능 — 음성만 내보내기 (사용자 요청).
v1: single-source video_track + cut 효과 적용. multi-source / speed / b-roll 은 v2.
"""
from __future__ import annotations

import pytest

from screen_recorder.effects.sidecar import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.encode.audio_export import (
    AudioExportSettings,
    build_audio_export_args,
    compute_audio_keep_intervals,
)


# ============================================================
# AudioExportSettings — 검증
# ============================================================
def test_settings_defaults():
    s = AudioExportSettings()
    assert s.format == "mp3"
    assert s.channels == 2
    assert s.sample_rate == 44100
    assert s.mp3_bitrate == 192


def test_settings_invalid_format_rejected():
    with pytest.raises(ValueError, match="format"):
        AudioExportSettings(format="ogg")


def test_settings_invalid_channels_rejected():
    with pytest.raises(ValueError, match="channels"):
        AudioExportSettings(channels=3)


def test_settings_invalid_sample_rate_rejected():
    with pytest.raises(ValueError, match="sample_rate"):
        AudioExportSettings(sample_rate=12345)


def test_settings_mp3_bitrate_range():
    AudioExportSettings(mp3_bitrate=128)
    AudioExportSettings(mp3_bitrate=320)
    with pytest.raises(ValueError, match="bitrate"):
        AudioExportSettings(mp3_bitrate=1000)


# ============================================================
# compute_audio_keep_intervals — sidecar → keep ms 구간
# ============================================================
def _sc_with_one_segment(src="x.mp4", src_in=0, src_out=10_000, cuts=()):
    seg = VideoSegment(src=src, src_in_ms=src_in, src_out_ms=src_out,
                       src_duration_ms=src_out, start_ms=0)
    return Sidecar(
        source_path=src, source_hash="h",
        video_track=[seg],
        effects=[CutEffect(in_ms=c[0], out_ms=c[1]) for c in cuts],
    )


def test_compute_no_cuts_returns_full_range():
    sc = _sc_with_one_segment(src_in=0, src_out=10_000)
    src, keep = compute_audio_keep_intervals(sc)
    assert src == "x.mp4"
    assert keep == [(0, 10_000)]


def test_compute_one_cut_splits_into_two():
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(3000, 5000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(0, 3000), (5000, 10_000)]


def test_compute_two_cuts_three_intervals():
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(2000, 3000), (6000, 7000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(0, 2000), (3000, 6000), (7000, 10_000)]


def test_compute_cut_at_start_drops_head():
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(0, 2000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(2000, 10_000)]


def test_compute_cut_at_end_drops_tail():
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(8000, 10_000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(0, 8000)]


def test_compute_overlapping_cuts_handled():
    """겹치는 cut 들도 정확히 처리 (정렬 + 흡수)."""
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(2000, 4000), (3000, 5000)])
    _src, keep = compute_audio_keep_intervals(sc)
    # 둘이 겹치므로 결과는 (0, 2000) + (5000, 10000).
    assert keep == [(0, 2000), (5000, 10_000)]


def test_compute_splice_cuts_ignored():
    """splice (in==out) 는 0 폭 — keep 영향 없음."""
    sc = _sc_with_one_segment(src_in=0, src_out=10_000,
                                cuts=[(3000, 3000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(0, 10_000)]


def test_compute_respects_src_trim():
    """segment.src_in/out 가 0 이 아니면 그 범위가 시작점."""
    sc = _sc_with_one_segment(src_in=1000, src_out=8000, cuts=[(3000, 4000)])
    _src, keep = compute_audio_keep_intervals(sc)
    assert keep == [(1000, 3000), (4000, 8000)]


def test_compute_empty_track_raises():
    sc = Sidecar(source_path="x", source_hash="h", video_track=[], effects=[])
    with pytest.raises(ValueError, match="video_track"):
        compute_audio_keep_intervals(sc)


def test_compute_multi_source_raises_notimplemented():
    """v1 — 여러 src 가 섞이면 명확히 거부."""
    seg1 = VideoSegment(src="a.mp4", src_in_ms=0, src_out_ms=5000,
                         src_duration_ms=5000, start_ms=0)
    seg2 = VideoSegment(src="b.mp4", src_in_ms=0, src_out_ms=3000,
                         src_duration_ms=3000, start_ms=5000)
    sc = Sidecar(source_path="a.mp4", source_hash="h",
                  video_track=[seg1, seg2], effects=[])
    with pytest.raises(NotImplementedError, match="v1"):
        compute_audio_keep_intervals(sc)


# ============================================================
# build_audio_export_args — ffmpeg argv
# ============================================================
def test_build_simple_mp3_no_cuts():
    """단순 변환 (cut 없음) — filter_complex 없이 -vn."""
    args = build_audio_export_args(
        src_path="in.mp4",
        keep_intervals=[(0, 10_000)],
        settings=AudioExportSettings(format="mp3", channels=2, sample_rate=44100,
                                       mp3_bitrate=192),
        dst_path="out.mp3",
    )
    assert args[0] == "ffmpeg"
    assert "-i" in args and "in.mp4" in args
    assert "-vn" in args, "단일 keep 구간이면 -vn 단순 변환"
    assert "-ac" in args and "2" in args
    assert "-ar" in args and "44100" in args
    assert "-c:a" in args and "libmp3lame" in args
    assert "-b:a" in args and "192k" in args
    assert args[-1] == "out.mp3"


def test_build_wav_uses_pcm_codec():
    args = build_audio_export_args(
        src_path="in.mp4", keep_intervals=[(0, 10_000)],
        settings=AudioExportSettings(format="wav", channels=1, sample_rate=48000),
        dst_path="out.wav",
    )
    assert "-c:a" in args and "pcm_s16le" in args
    # wav 는 비트레이트 무의미 → -b:a 없음.
    assert "-b:a" not in args


def test_build_with_one_cut_uses_filter_complex():
    args = build_audio_export_args(
        src_path="in.mp4",
        keep_intervals=[(0, 3000), (5000, 10_000)],
        settings=AudioExportSettings(),
        dst_path="out.mp3",
    )
    # filter_complex 의 atrim + concat.
    assert "-filter_complex" in args
    idx = args.index("-filter_complex")
    filt = args[idx + 1]
    assert "atrim=start=0.000:end=3.000" in filt
    assert "atrim=start=5.000:end=10.000" in filt
    assert "concat=n=2:v=0:a=1" in filt
    assert "-map" in args and "[aout]" in args
    assert "-vn" not in args, "filter_complex 사용 시 -vn 대신 -map 으로 처리"


def test_build_mono_channels():
    args = build_audio_export_args(
        src_path="in.mp4", keep_intervals=[(0, 10_000)],
        settings=AudioExportSettings(channels=1), dst_path="out.mp3",
    )
    i = args.index("-ac")
    assert args[i + 1] == "1"


def test_build_high_sample_rate():
    args = build_audio_export_args(
        src_path="in.mp4", keep_intervals=[(0, 10_000)],
        settings=AudioExportSettings(sample_rate=48000), dst_path="out.mp3",
    )
    i = args.index("-ar")
    assert args[i + 1] == "48000"


def test_build_empty_keep_raises():
    """전체가 cut 처리되면 빈 keep → ValueError (의미 없음)."""
    with pytest.raises(ValueError, match="keep"):
        build_audio_export_args(
            src_path="in.mp4", keep_intervals=[],
            settings=AudioExportSettings(), dst_path="out.mp3",
        )
