"""subtitle_export — Transcript → TXT / SRT 직렬화 + Settings 검증.

2026-05-20 신규 (사용자 요청). 사용자 명시: "Whisper 로 새로 생성. txt 디폴트,
srt 도 고를 수 있게." 모델 선택 가능.
"""
from __future__ import annotations

import pytest

from screen_recorder.agent.transcript import Transcript, TranscriptSegment
from screen_recorder.encode.subtitle_export import (
    SubtitleExportSettings,
    remap_segments_for_cuts,
    segments_to_srt,
    segments_to_txt,
)


def _make_segs():
    return [
        TranscriptSegment(start_ms=0, end_ms=2500, text="안녕하세요"),
        TranscriptSegment(start_ms=2500, end_ms=5000, text="반갑습니다 여러분"),
        TranscriptSegment(start_ms=5000, end_ms=8200, text="오늘은 KStudio 를 소개합니다"),
    ]


# ============================================================
# SubtitleExportSettings 검증
# ============================================================
def test_settings_defaults():
    s = SubtitleExportSettings()
    assert s.format == "txt"   # 사용자 명시 — txt 디폴트
    assert s.model_size == "base"


def test_settings_invalid_format_rejected():
    with pytest.raises(ValueError, match="format"):
        SubtitleExportSettings(format="vtt")


def test_settings_invalid_model_rejected():
    with pytest.raises(ValueError, match="model"):
        SubtitleExportSettings(model_size="huge")


def test_settings_all_valid_models():
    for m in ("tiny", "base", "small", "medium", "large-v3"):
        SubtitleExportSettings(model_size=m)


# ============================================================
# segments_to_txt — 단순 텍스트 (한 줄 한 자막)
# ============================================================
def test_txt_one_line_per_segment():
    out = segments_to_txt(_make_segs())
    lines = out.splitlines()
    assert lines == [
        "안녕하세요",
        "반갑습니다 여러분",
        "오늘은 KStudio 를 소개합니다",
    ]


def test_txt_empty_segments():
    assert segments_to_txt([]) == ""


def test_txt_strips_segment_text():
    """앞뒤 공백 제거 (whisper 가 종종 leading space 붙임)."""
    segs = [TranscriptSegment(start_ms=0, end_ms=1000, text="  hi  ")]
    assert segments_to_txt(segs) == "hi"


# ============================================================
# segments_to_srt — 타임코드 포함
# ============================================================
def test_srt_format_basic():
    """SRT 표준 — 번호 + '00:00:00,000 --> 00:00:00,000' + 본문 + 빈 줄."""
    out = segments_to_srt(_make_segs())
    # 첫 자막 확인.
    assert out.startswith("1\n00:00:00,000 --> 00:00:02,500\n안녕하세요\n\n")
    # 두 번째.
    assert "2\n00:00:02,500 --> 00:00:05,000\n반갑습니다 여러분\n\n" in out
    # 마지막 자막은 trailing blank line 1개.
    assert out.endswith("\n\n")


def test_srt_timecode_handles_hours():
    """1시간 넘는 ms 도 정확히 H:MM:SS,mmm."""
    segs = [TranscriptSegment(start_ms=3_600_000, end_ms=3_605_500,
                                text="한 시간 지났습니다")]
    out = segments_to_srt(segs)
    assert "01:00:00,000 --> 01:00:05,500" in out


def test_srt_timecode_uses_comma_not_dot():
    """SRT 표준은 ms 구분자가 콤마. WebVTT 와 다름 (점 사용)."""
    segs = [TranscriptSegment(start_ms=1234, end_ms=5678, text="x")]
    out = segments_to_srt(segs)
    assert "00:00:01,234" in out
    assert "00:00:05,678" in out
    # 점은 timecode 부분에 없어야.
    timecode_line = [l for l in out.splitlines() if "-->" in l][0]
    assert "." not in timecode_line


def test_srt_index_starts_at_one_not_zero():
    out = segments_to_srt(_make_segs())
    first_line = out.splitlines()[0]
    assert first_line == "1"


def test_srt_empty_segments():
    assert segments_to_srt([]) == ""


def test_srt_strips_segment_text():
    segs = [TranscriptSegment(start_ms=0, end_ms=1000, text="  hi  ")]
    out = segments_to_srt(segs)
    # 텍스트 부분만 추출.
    assert "\nhi\n" in out


# ============================================================
# 라운드트립 — 시간 정확도
# ============================================================
def test_srt_exact_timecode_zero():
    segs = [TranscriptSegment(start_ms=0, end_ms=0, text="x")]
    out = segments_to_srt(segs)
    assert "00:00:00,000 --> 00:00:00,000" in out


def test_srt_subsecond_precision():
    """ms 정밀도 유지 (47ms 가 047 로)."""
    segs = [TranscriptSegment(start_ms=47, end_ms=999, text="x")]
    out = segments_to_srt(segs)
    assert "00:00:00,047 --> 00:00:00,999" in out


# ============================================================
# remap_segments_for_cuts — 사이드카 cut 적용 → 편집본 시간축
# 2026-05-20 사용자 결정: SRT 자막은 편집 결과 영상 기준.
# ============================================================
def test_remap_no_cuts_returns_segments_unchanged():
    """keep == 전체 = (0, 10000) 면 segments 그대로."""
    segs = [
        TranscriptSegment(start_ms=1000, end_ms=2000, text="a"),
        TranscriptSegment(start_ms=3000, end_ms=4000, text="b"),
    ]
    out = remap_segments_for_cuts(segs, [(0, 10_000)])
    assert len(out) == 2
    assert out[0].start_ms == 1000 and out[0].end_ms == 2000
    assert out[1].start_ms == 3000 and out[1].end_ms == 4000


def test_remap_drops_segments_inside_cut():
    """cut [2000, 5000] — keep [(0,2000), (5000,10000)]. 가운데 segment 제거."""
    segs = [
        TranscriptSegment(start_ms=500, end_ms=1500, text="a"),    # keep1 안
        TranscriptSegment(start_ms=3000, end_ms=4000, text="b"),   # cut 안 → drop
        TranscriptSegment(start_ms=6000, end_ms=7000, text="c"),   # keep2 안
    ]
    out = remap_segments_for_cuts(segs, [(0, 2000), (5000, 10_000)])
    assert [s.text for s in out] == ["a", "c"]


def test_remap_shifts_later_segments_to_edited_timeline():
    """cut [2000,5000] 후 keep2 = (5000,10000). 편집본에서 keep2 는 2000ms 부터 시작.
    segment c (원본 6000-7000) → 편집본 3000-4000 으로 shift.
    """
    segs = [
        TranscriptSegment(start_ms=500, end_ms=1500, text="a"),
        TranscriptSegment(start_ms=6000, end_ms=7000, text="c"),
    ]
    out = remap_segments_for_cuts(segs, [(0, 2000), (5000, 10_000)])
    # a 는 keep1 안 — 변화 없음.
    assert out[0].start_ms == 500 and out[0].end_ms == 1500
    # c 는 keep2 안 — keep2 의 원본 시작 5000 이 편집본 2000 → offset -3000.
    # 원본 6000-7000 → 편집본 3000-4000.
    assert out[1].start_ms == 3000 and out[1].end_ms == 4000


def test_remap_keep_start_offset_handled():
    """첫 keep 이 (1000, 5000) 으로 시작점이 0 아님 — segment 도 그만큼 앞당김."""
    segs = [TranscriptSegment(start_ms=2000, end_ms=3000, text="a")]
    out = remap_segments_for_cuts(segs, [(1000, 5000)])
    # keep 시작 = 원본 1000 = 편집본 0. offset = -1000.
    assert out[0].start_ms == 1000
    assert out[0].end_ms == 2000


def test_remap_segment_overlapping_cut_boundary_dropped():
    """segment 가 cut 경계에 걸쳐 있으면 중심 기준 — 중심이 cut 안이면 drop."""
    segs = [
        # 1500-3500 — 중심 2500 → cut [2000,5000] 안 → drop.
        TranscriptSegment(start_ms=1500, end_ms=3500, text="dropped"),
    ]
    out = remap_segments_for_cuts(segs, [(0, 2000), (5000, 10_000)])
    assert out == []


def test_remap_empty_keep_returns_empty():
    """전체가 cut 처리되어 keep 없으면 empty."""
    segs = [TranscriptSegment(start_ms=1000, end_ms=2000, text="a")]
    out = remap_segments_for_cuts(segs, [])
    assert out == []


def test_remap_preserves_text():
    """text 는 원본 그대로 보존 (시간만 remap)."""
    segs = [TranscriptSegment(start_ms=6000, end_ms=7000, text="안녕하세요")]
    out = remap_segments_for_cuts(segs, [(0, 2000), (5000, 10_000)])
    assert out[0].text == "안녕하세요"
