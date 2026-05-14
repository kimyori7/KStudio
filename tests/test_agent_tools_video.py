"""Claude 에이전트의 read-only 비디오 도구 — Phase A.

활성 영상 없을 때 / 빈 사이드카 / 효과 다수 시나리오. SDK 의 mcp_server() 가
반환하는 도구 함수는 직접 await 하기 어려우므로 (SdkMcpTool wrapper),
adapter + 헬퍼 함수(_sidecar_summary_text, _effect_summary 등) 단위로 검증.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from screen_recorder.agent.tools_video import (
    VideoTools, _sidecar_summary_text, _format_ms_short,
)
from screen_recorder.effects import Sidecar
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.arrow import ArrowEffect, Point


@dataclass
class _FakeAdapter:
    """테스트용 어댑터 — VideoSessionAdapter Protocol 만족."""
    has_video: bool = True
    src_path: Optional[str] = "C:/test/video.mp4"
    dur_ms: int = 60_000
    pos_ms: int = 0
    sc: Optional[Sidecar] = None

    def has_active_video(self) -> bool: return self.has_video
    def source_path(self) -> Optional[str]: return self.src_path if self.has_video else None
    def duration_ms(self) -> int: return self.dur_ms if self.has_video else 0
    def position_ms(self) -> int: return self.pos_ms if self.has_video else 0
    def sidecar(self):
        return self.sc if self.has_video else None


def _make_sidecar_with_effects() -> Sidecar:
    sc = Sidecar(source_path="C:/test/video.mp4", source_hash="hash")
    sc.video_track.append(VideoSegment(
        src="C:/test/video.mp4", src_in_ms=0, src_out_ms=60_000,
        src_duration_ms=60_000, media_kind="video",
    ))
    sc.effects = [
        CaptionEffect(in_ms=1_000, out_ms=3_000, text="안녕", track_idx=0),
        CaptionEffect(in_ms=10_000, out_ms=12_000, text="잘있어", track_idx=1),
        SpeedEffect(in_ms=20_000, out_ms=25_000, rate=2.0),
        ArrowEffect(in_ms=30_000, out_ms=32_000,
                     start=Point(x=0.2, y=0.5), end=Point(x=0.8, y=0.5), track_idx=0),
    ]
    return sc


# ============================================================
# 요약 헬퍼
# ============================================================
def test_summary_empty_sidecar() -> None:
    sc = Sidecar()
    txt = _sidecar_summary_text(sc, duration_ms=0)
    assert "효과 없음" in txt
    assert "세그먼트 0" in txt


def test_summary_with_effects() -> None:
    sc = _make_sidecar_with_effects()
    txt = _sidecar_summary_text(sc, duration_ms=60_000)
    assert "효과 4개" in txt
    assert "캡션 2" in txt
    assert "배속 1" in txt
    assert "화살표 1" in txt
    # 한 문단 — 너무 길지 않아야 (Claude RAM 절약 목적).
    assert len(txt) < 200, f"summary too long: {len(txt)}: {txt}"


def test_format_ms_short_ranges() -> None:
    assert _format_ms_short(0) == "0:00.0"
    assert _format_ms_short(123_456) == "2:03.4"
    assert _format_ms_short(3_661_000) == "1:01:01"


# ============================================================
# tool_names — allowed_tools 검증
# ============================================================
def test_tool_names_prefix_correct() -> None:
    vt = VideoTools(_FakeAdapter())
    names = vt.tool_names()
    assert all(n.startswith("mcp__kstudio_video__") for n in names)
    # antipattern get_effects_sidecar 가 surface 에서 사라졌어야 — 통째 덤프 금지.
    assert not any("get_effects_sidecar" in n for n in names)
    # 새 도구 둘이 있어야.
    assert any("get_sidecar_summary" in n for n in names)
    assert any("get_effects_in_range" in n for n in names)


def test_tool_count_includes_visual() -> None:
    """read 8 + visual 2 + mutation 6 + preview 1 = 17 도구 (transcript ctx 제외).

    2026-05-13: list_broll_sources 추가 → read 7 → 8.
    """
    vt = VideoTools(_FakeAdapter())
    names = vt.tool_names()
    assert len(names) == 17
    assert any("get_frame_at" in n for n in names)
    assert any("get_timeline_strip" in n for n in names)
    assert any("propose_effect" in n for n in names)
    assert any("propose_remove_effect" in n for n in names)
    assert any("propose_modify_effect" in n for n in names)
    assert any("apply_proposals" in n for n in names)
    assert any("inspect_effect" in n for n in names)
    assert any("preview_proposal" in n for n in names)
    assert any("list_broll_sources" in n for n in names)


# ============================================================
# mcp_server 빌드 검증
# ============================================================
def test_mcp_server_builds() -> None:
    """create_sdk_mcp_server 가 에러 없이 서버 인스턴스 반환."""
    vt = VideoTools(_FakeAdapter())
    srv = vt.mcp_server()
    assert srv is not None


# ============================================================
# 어댑터 통합 — 비디오 없을 때
# ============================================================
def test_adapter_no_video() -> None:
    adapter = _FakeAdapter(has_video=False)
    assert adapter.has_active_video() is False
    assert adapter.duration_ms() == 0
    assert adapter.sidecar() is None


# ============================================================
# Phase C — 비주얼 도구
# ============================================================
def test_visual_tools_disabled_without_ffmpeg_path() -> None:
    """ffmpeg_path=None 이면 도구는 등록되지만 호출 시 에러 응답.

    호출 검증은 비동기라 여기선 surface 만 — 7개 다 등록됐는지.
    """
    vt = VideoTools(_FakeAdapter(), ffmpeg_path=None)
    names = vt.tool_names()
    assert any("get_frame_at" in n for n in names)
    assert any("get_timeline_strip" in n for n in names)


def test_get_video_state_includes_effects_by_type() -> None:
    """get_video_state 가 effects_by_type 종류별 breakdown 반환 (회귀 보호).

    2026-05-13 사용자 보고: n_effects=N 만 보고 '컷 N개' 라고 hallucination 했음.
    종류별 0 포함 명시 → 에이전트가 종류 추측 불가능.
    """
    import asyncio

    sc = _make_sidecar_with_effects()
    adapter = _FakeAdapter(sc=sc)
    vt = VideoTools(adapter)
    # mcp_server 빌드 후 직접 호출은 어려우니 read.py 의 빌더 함수 직접 사용.
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    # 첫 번째 도구가 get_video_state.
    get_state = tools[0]
    # SdkMcpTool wrapper — handler 가 실제 async 함수.
    import json
    result = asyncio.run(get_state.handler({}))
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert "effects_by_type" in payload
    by_type = payload["effects_by_type"]
    # _make_sidecar_with_effects: caption 2, speed 1, arrow 1, cut 0.
    assert by_type["caption"] == 2
    assert by_type["speed"] == 1
    assert by_type["arrow"] == 1
    assert by_type["cut"] == 0
    assert by_type["zoom"] == 0
    assert by_type["broll"] == 0
    # n_effects 도 일치.
    assert payload["n_effects"] == 4


def test_get_video_state_empty_sidecar_has_all_types_zero() -> None:
    """효과 0개여도 effects_by_type 의 모든 키가 0 으로 존재 — 'cut 누락 → 추측' 차단."""
    import asyncio
    import json

    sc = Sidecar()
    adapter = _FakeAdapter(sc=sc)
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    get_state = tools[0]
    result = asyncio.run(get_state.handler({}))
    payload = json.loads(result["content"][0]["text"])
    assert payload["n_effects"] == 0
    by_type = payload["effects_by_type"]
    for t in ("cut", "caption", "speed", "zoom", "broll", "arrow"):
        assert by_type.get(t) == 0, f"{t} 키 누락 또는 비-0: {by_type}"


# ============================================================
# source_duration 분리 — 2026-05-14 사용자 보고 회귀 보호.
# "여전히 3분24초짜리를 2분으로 착각하는데"
# 원인: 에이전트는 duration_ms (combined, cuts 후) 만 봐서 source 길이 모름.
# 사이드카에 cuts 가 있으면 combined < source → 사용자 환각 오해.
# ============================================================
@dataclass
class _FakeAdapterWithSource(_FakeAdapter):
    """source_duration_ms 메서드 있는 어댑터."""
    source_dur_ms: int = 0

    def source_duration_ms(self) -> int:
        return self.source_dur_ms if self.has_video else 0


def test_get_video_state_exposes_three_durations() -> None:
    """get_video_state 가 source / duration / export 세 길이를 정확히 분리.

    사용자 사례 (2026-05-14): 원본 3:24 (204267ms), cut 2개 (22s + 62s) 등록됨.
    KStudio cut 효과는 편집 타임라인에 *즉시 적용 안 됨* → duration_ms = source.
    export_duration_ms 는 source - 등록된 cut 합 = 120267ms 로 *예상* 길이.
    """
    import asyncio
    import json

    from screen_recorder.effects.types.cut import CutEffect
    sc = Sidecar(source_path="C:/x.mp4", source_hash="h")
    sc.effects = [
        CutEffect(in_ms=18_000, out_ms=40_000),
        CutEffect(in_ms=75_000, out_ms=137_000),
    ]
    # 실제 KStudio 동작: 편집 타임라인은 source 와 같음 (cut 즉시 적용 안 됨).
    adapter = _FakeAdapterWithSource(sc=sc, dur_ms=204_267, source_dur_ms=204_267)
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    get_state = tools[0]
    result = asyncio.run(get_state.handler({}))
    payload = json.loads(result["content"][0]["text"])
    assert payload["source_duration_ms"] == 204_267
    assert payload["duration_ms"] == 204_267   # 편집 타임라인은 cut 즉시 적용 안 됨
    assert payload["export_duration_ms"] == 120_267   # 204267 - (22000 + 62000)
    assert payload["cut_planned_ms"] == 84_000
    assert payload["cut_count_planned"] == 2
    # effects_by_type 의 cut 개수는 그대로 2.
    assert payload["effects_by_type"]["cut"] == 2


def test_get_video_state_cut_with_broll_insert_not_counted_as_removal() -> None:
    """B-roll 삽입 cut (src 있음) 은 cut_planned_ms 에서 제외 — replace 라 길이 안 줄어듦."""
    import asyncio
    import json

    from screen_recorder.effects.types.cut import CutEffect
    sc = Sidecar(source_path="C:/x.mp4", source_hash="h")
    sc.effects = [
        CutEffect(in_ms=10_000, out_ms=20_000),                              # 단순 자르기
        CutEffect(in_ms=30_000, out_ms=40_000, src="C:/broll.mp4",
                   src_in_ms=0, src_out_ms=10_000, src_duration_ms=10_000),  # B-roll 삽입
    ]
    adapter = _FakeAdapterWithSource(sc=sc, dur_ms=60_000, source_dur_ms=60_000)
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    get_state = tools[0]
    payload = json.loads(asyncio.run(get_state.handler({}))["content"][0]["text"])
    # 단순 자르기만 합산 — 10000ms. B-roll cut 제외.
    assert payload["cut_planned_ms"] == 10_000
    assert payload["cut_count_planned"] == 1
    # 하지만 effects_by_type 엔 둘 다 cut.
    assert payload["effects_by_type"]["cut"] == 2


def test_get_video_state_splice_point_not_counted() -> None:
    """in_ms == out_ms (splice 점) 인 cut 은 cut_planned_ms 에 포함 안 됨 — 길이 0."""
    import asyncio
    import json

    from screen_recorder.effects.types.cut import CutEffect
    sc = Sidecar(source_path="C:/x.mp4", source_hash="h")
    sc.effects = [
        CutEffect(in_ms=15_000, out_ms=15_000),   # splice (in == out)
    ]
    adapter = _FakeAdapterWithSource(sc=sc, dur_ms=60_000, source_dur_ms=60_000)
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    payload = json.loads(asyncio.run(tools[0].handler({}))["content"][0]["text"])
    assert payload["cut_planned_ms"] == 0
    assert payload["cut_count_planned"] == 0
    assert payload["effects_by_type"]["cut"] == 1   # splice 도 type 카운트엔 들어감


def test_get_video_state_source_falls_back_to_combined_when_unknown() -> None:
    """어댑터가 source_duration_ms 미구현 / 0 반환 시 combined 로 fallback → None 회피."""
    import asyncio
    import json

    sc = Sidecar()
    adapter = _FakeAdapter(sc=sc, dur_ms=60_000)
    from screen_recorder.agent.tools.read import make_read_tools
    tools = make_read_tools(adapter)
    get_state = tools[0]
    result = asyncio.run(get_state.handler({}))
    payload = json.loads(result["content"][0]["text"])
    assert payload["source_duration_ms"] == 60_000
    assert payload["duration_ms"] == 60_000
    assert payload["export_duration_ms"] == 60_000   # cut 없으니 source 와 같음
    assert payload["cut_planned_ms"] == 0
    assert payload["cut_count_planned"] == 0


def test_image_result_format() -> None:
    """_image_result 가 MCP image content 표준 (base64 + mimeType) 따르는지."""
    from screen_recorder.agent.tools_video import _image_result
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    res = _image_result(fake_png, caption="test")
    assert res["content"][0]["type"] == "text"
    assert res["content"][0]["text"] == "test"
    img = res["content"][1]
    assert img["type"] == "image"
    assert img["mimeType"] == "image/png"
    # base64 디코딩 가능 + 원본 일치.
    import base64
    assert base64.b64decode(img["data"]) == fake_png


def test_composite_timeline_strip_input_validation() -> None:
    """composite_timeline_strip 의 인자 검증 — n<=0 거부, end<=start 시 n=1 로 fallback."""
    from screen_recorder.agent.frame_extractor import composite_timeline_strip
    with pytest.raises(ValueError):
        composite_timeline_strip("nonexistent.mp4", 0, 1000, 0, "ffmpeg")
    # end<=start 일 때 — 실제 ffmpeg 호출은 실패하나 우리 validation 단계는 통과 (n=1 로 fallback).
    # 실제 ffmpeg 호출 검증은 통합테스트로 별도.
