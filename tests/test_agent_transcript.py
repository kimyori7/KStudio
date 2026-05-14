"""Phase D — Whisper 자막 추출 + 캐시 (실제 모델 호출 X — 캐시 I/O + 도구 surface만)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from screen_recorder.agent.transcript import (
    TRANSCRIPT_EXT, TRANSCRIPT_SCHEMA_VERSION, Transcript, TranscriptSegment,
    VALID_MODEL_SIZES, load_transcript, save_transcript, transcript_path_for,
)


# ============================================================
# Transcript dataclass + 직렬화
# ============================================================
def _sample_transcript() -> Transcript:
    return Transcript(
        source_hash="abc123",
        model_size="base",
        language="ko",
        duration_ms=10_000,
        segments=[
            TranscriptSegment(start_ms=0, end_ms=2_500, text="안녕하세요."),
            TranscriptSegment(start_ms=3_000, end_ms=5_000, text="오늘은 날씨가 좋네요."),
            TranscriptSegment(start_ms=6_500, end_ms=9_000, text="모두 좋은 하루 보내세요."),
        ],
    )


def test_transcript_roundtrip_dict() -> None:
    t = _sample_transcript()
    d = t.to_dict()
    assert d["version"] == TRANSCRIPT_SCHEMA_VERSION
    assert d["source_hash"] == "abc123"
    assert len(d["segments"]) == 3
    t2 = Transcript.from_dict(d)
    assert t2.duration_ms == t.duration_ms
    assert t2.segments[0].text == "안녕하세요."


def test_transcript_segments_in_range() -> None:
    t = _sample_transcript()
    # 4~7초 → 2번째(3-5s) + 3번째(6.5-9s) 둘 다 포함.
    in_range = t.segments_in_range(4_000, 7_000)
    assert len(in_range) == 2
    # 0~1초 → 첫 segment 만.
    in_range = t.segments_in_range(0, 1_000)
    assert len(in_range) == 1
    assert in_range[0].text == "안녕하세요."
    # 9.5~10s → 어떤 segment 도 포함 안 됨.
    in_range = t.segments_in_range(9_500, 10_000)
    assert len(in_range) == 0


def test_transcript_save_load_roundtrip(tmp_path: Path) -> None:
    t = _sample_transcript()
    path = tmp_path / "test.transcript.json"
    save_transcript(path, t)
    assert path.exists()
    loaded = load_transcript(path)
    assert loaded is not None
    assert loaded.source_hash == "abc123"
    assert len(loaded.segments) == 3
    assert loaded.segments[1].text == "오늘은 날씨가 좋네요."


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_transcript(tmp_path / "no.transcript.json") is None


def test_load_corrupted_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.transcript.json"
    path.write_text("not valid json", encoding="utf-8")
    assert load_transcript(path) is None


def test_load_wrong_version_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "wrong_ver.transcript.json"
    path.write_text(json.dumps({"version": 999, "segments": []}), encoding="utf-8")
    assert load_transcript(path) is None


def test_transcript_path_uses_basename_and_hash(tmp_path: Path) -> None:
    p = transcript_path_for(tmp_path, Path("C:/videos/sample.mp4"), "deadbeef")
    assert p.parent == tmp_path
    assert p.name == "sample_deadbeef" + TRANSCRIPT_EXT


def test_transcript_path_sanitizes_basename(tmp_path: Path) -> None:
    """파일 시스템 금지 문자가 제거되어야."""
    p = transcript_path_for(tmp_path, Path("C:/videos/bad<name>.mp4"), "abc")
    assert "<" not in p.name and ">" not in p.name
    assert p.name.endswith(TRANSCRIPT_EXT)


# ============================================================
# 도구 surface
# ============================================================
def test_transcript_tools_count() -> None:
    """transcript_ctx 주입 시 도구 surface 17 → 21 (전사 4개 추가)."""
    from screen_recorder.agent.tools import VideoTools

    class _Adapter:
        def has_active_video(self): return False
        def source_path(self): return None
        def duration_ms(self): return 0
        def position_ms(self): return 0
        def sidecar(self): return None

    class _Ctx:
        def sidecar_dir(self): return Path("./tmp")
        def source_hash(self): return None
        def default_model_size(self): return "base"

    vt_no_ctx = VideoTools(_Adapter())
    assert len(vt_no_ctx.tool_names()) == 17, "transcript_ctx 없으면 자막 도구 비활성"

    vt_with_ctx = VideoTools(_Adapter(), transcript_ctx=_Ctx())
    names = vt_with_ctx.tool_names()
    # read 8 + visual 2 + mutation 6 + preview 1 + transcript 4 = 21.
    assert len(names) == 21
    for required in (
        "transcribe_video", "get_transcript_range", "get_transcript_status",
        "download_whisper_model",
    ):
        assert any(required in n for n in names), f"missing tool: {required}"


def test_valid_model_sizes() -> None:
    assert "base" in VALID_MODEL_SIZES
    assert "tiny" in VALID_MODEL_SIZES
    assert "medium" in VALID_MODEL_SIZES
    assert "invalid" not in VALID_MODEL_SIZES
