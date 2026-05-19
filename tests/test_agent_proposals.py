"""Phase B — 편집 제안 큐 + 검증 + Effect 빌더.

UI 마샬링 / SDK 호출은 통합 테스트에서. 여기서는 도메인 로직만.
"""
from __future__ import annotations

import threading

import pytest

from screen_recorder.agent.proposals import (
    EffectProposal, ProposalQueue, VALID_TYPES,
    validate_payload, build_effect_from_proposal,
)


# ============================================================
# ProposalQueue — thread safety + 기본 동작
# ============================================================
def test_queue_empty_by_default() -> None:
    q = ProposalQueue()
    assert q.count() == 0
    assert q.list() == []


def test_queue_add_list_take_clear() -> None:
    q = ProposalQueue()
    q.add(EffectProposal(type="caption", payload={"in_ms": 0, "out_ms": 1000, "text": "a"}))
    q.add(EffectProposal(type="caption", payload={"in_ms": 1000, "out_ms": 2000, "text": "b"}))
    assert q.count() == 2
    snapshot = q.list()
    assert len(snapshot) == 2
    assert snapshot[0].payload["text"] == "a"
    # list 가 내부 ref 가 아닌 copy 임 — 외부 변경 안 새어들어감.
    snapshot.clear()
    assert q.count() == 2
    taken = q.take_all()
    assert len(taken) == 2
    assert q.count() == 0
    # clear 는 빈 큐에도 OK.
    q.clear()
    assert q.count() == 0


def test_queue_thread_safety_concurrent_add() -> None:
    """여러 스레드에서 동시 add — count 정확."""
    q = ProposalQueue()
    def add_many(n: int) -> None:
        for i in range(n):
            q.add(EffectProposal(type="cut", payload={"in_ms": i, "out_ms": i}))
    threads = [threading.Thread(target=add_many, args=(100,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert q.count() == 500


# ============================================================
# validate_payload — type 별 필수 필드
# ============================================================
def test_validate_unknown_type() -> None:
    err = validate_payload("madeup", {"in_ms": 0, "out_ms": 1000})
    assert err is not None
    assert "unknown" in err.lower()


def test_validate_missing_in_out_ms() -> None:
    err = validate_payload("caption", {"text": "hi"})
    assert err is not None
    assert "in_ms" in err


def test_validate_out_before_in() -> None:
    err = validate_payload("caption", {"in_ms": 2000, "out_ms": 1000, "text": "hi"})
    assert err is not None
    assert "out_ms" in err and "in_ms" in err


def test_validate_cut_allows_zero_width() -> None:
    """cut 은 out_ms==in_ms 가 splice point (유효)."""
    err = validate_payload("cut", {"in_ms": 5000, "out_ms": 5000})
    assert err is None


def test_validate_caption_requires_text() -> None:
    err = validate_payload("caption", {"in_ms": 0, "out_ms": 1000})
    assert err is not None
    assert "text" in err


def test_validate_speed_requires_rate() -> None:
    err = validate_payload("speed", {"in_ms": 0, "out_ms": 1000})
    assert err is not None
    assert "rate" in err


def test_validate_speed_rate_range() -> None:
    err = validate_payload("speed", {"in_ms": 0, "out_ms": 1000, "rate": 0})
    assert err is not None
    err = validate_payload("speed", {"in_ms": 0, "out_ms": 1000, "rate": 100})
    assert err is not None
    err = validate_payload("speed", {"in_ms": 0, "out_ms": 1000, "rate": 2.0})
    assert err is None


def test_validate_broll_requires_src() -> None:
    err = validate_payload("broll", {"in_ms": 0, "out_ms": 1000})
    assert err is not None
    assert "src" in err


def test_validate_happy_paths() -> None:
    cases = [
        ("caption", {"in_ms": 0, "out_ms": 1000, "text": "hi"}),
        ("cut", {"in_ms": 5000, "out_ms": 5000}),
        ("speed", {"in_ms": 0, "out_ms": 2000, "rate": 1.5}),
        ("zoom", {"in_ms": 0, "out_ms": 2000,
                   "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
                   "end": {"x": 0.3, "y": 0.3, "scale": 2.0}}),
        ("broll", {"in_ms": 0, "out_ms": 5000, "src": "C:/test.mp4"}),
        ("arrow", {"in_ms": 0, "out_ms": 2000,
                    "start": {"x": 0.2, "y": 0.5}, "end": {"x": 0.8, "y": 0.5}}),
    ]
    for eff_type, payload in cases:
        assert validate_payload(eff_type, payload) is None, \
            f"happy path rejected for {eff_type}: {payload}"


# ============================================================
# build_effect_from_proposal — 6종 모두 빌드
# ============================================================
def test_build_caption() -> None:
    p = EffectProposal(type="caption",
                        payload={"in_ms": 0, "out_ms": 1000, "text": "안녕", "track_idx": 2})
    eff = build_effect_from_proposal(p)
    assert eff.type == "caption"
    assert eff.in_ms == 0 and eff.out_ms == 1000
    assert eff.text == "안녕"
    assert eff.track_idx == 2


def test_build_cut() -> None:
    p = EffectProposal(type="cut", payload={"in_ms": 5000, "out_ms": 5000})
    eff = build_effect_from_proposal(p)
    assert eff.type == "cut"


def test_build_speed() -> None:
    p = EffectProposal(type="speed", payload={"in_ms": 0, "out_ms": 2000, "rate": 2.0})
    eff = build_effect_from_proposal(p)
    assert eff.type == "speed"
    assert eff.rate == 2.0


def test_build_zoom() -> None:
    p = EffectProposal(type="zoom", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end": {"x": 0.3, "y": 0.3, "scale": 2.0},
    })
    eff = build_effect_from_proposal(p)
    assert eff.type == "zoom"
    assert eff.start.cx == 0.5 and eff.end.scale == 2.0


def test_build_broll() -> None:
    p = EffectProposal(type="broll", payload={
        "in_ms": 0, "out_ms": 5000, "src": "C:/test.mp4", "track_idx": 1,
    })
    eff = build_effect_from_proposal(p)
    assert eff.type == "broll"
    assert eff.src == "C:/test.mp4"
    assert eff.track_idx == 1


def test_build_broll_default_placement_is_pip() -> None:
    """2026-05-14 회귀 보호: propose 가 placement 명시 안 하면 'pip' 으로 들어가야.

    사용자 보고 "AI 가 곁들임 추가하면 여전히 안 보임" — BrollEffect.placement 기본값
    'fullscreen' 인데 propose 가 명시 안 해서 preview overlay 의 PIP 가이드가 skip.
    이제 propose 의 기본은 'pip' 으로 뒤집힘.
    """
    p = EffectProposal(type="broll", payload={
        "in_ms": 0, "out_ms": 5000, "src": "C:/test.mp4",
    })
    eff = build_effect_from_proposal(p)
    assert eff.placement == "pip"
    assert eff.pip is not None   # PiP 박스가 그려지려면 pip 설정 필수.


def test_build_broll_explicit_fullscreen() -> None:
    """사용자(에이전트) 가 명시적으로 fullscreen 원하면 그대로 통과."""
    p = EffectProposal(type="broll", payload={
        "in_ms": 0, "out_ms": 5000, "src": "C:/test.mp4",
        "placement": "fullscreen",
    })
    eff = build_effect_from_proposal(p)
    assert eff.placement == "fullscreen"
    # fullscreen 은 PiP 박스 없음.
    assert eff.pip is None


def test_validate_broll_invalid_placement_rejected() -> None:
    from screen_recorder.agent.proposals import validate_payload
    err = validate_payload("broll", {
        "in_ms": 0, "out_ms": 5000, "src": "C:/test.mp4",
        "placement": "popup",   # 유효하지 않음
    })
    assert err is not None
    assert "placement" in err


def test_build_arrow() -> None:
    p = EffectProposal(type="arrow", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.2, "y": 0.5}, "end": {"x": 0.8, "y": 0.5},
        "track_idx": 0,
    })
    eff = build_effect_from_proposal(p)
    assert eff.type == "arrow"
    assert eff.start.x == 0.2 and eff.end.x == 0.8


def test_build_unknown_raises() -> None:
    p = EffectProposal(type="madeup", payload={"in_ms": 0, "out_ms": 1000})
    with pytest.raises(ValueError):
        build_effect_from_proposal(p)


# ============================================================
# 도구 surface — Phase B 추가
# ============================================================
def test_tool_count_phase_b() -> None:
    """read 8 + visual 2 + mutation 7 + preview 1 = 18 (2026-05-19: submit_plan 추가)."""
    from screen_recorder.agent.tools_video import VideoTools
    class _Fake:
        def has_active_video(self): return False
        def source_path(self): return None
        def duration_ms(self): return 0
        def position_ms(self): return 0
        def sidecar(self): return None
    vt = VideoTools(_Fake())
    names = vt.tool_names()
    assert len(names) == 18
    for required in (
        "propose_effect", "propose_remove_effect", "propose_modify_effect",
        "list_proposals", "apply_proposals", "discard_proposals",
        "preview_proposal",
    ):
        assert any(required in n for n in names), f"missing tool: {required}"


# ============================================================
# Remove / Modify proposal 검증
# ============================================================
def test_remove_validate_requires_effect_id() -> None:
    from screen_recorder.agent.proposals import validate_remove_payload
    assert validate_remove_payload({}) is not None
    assert validate_remove_payload({"effect_id": ""}) is not None
    assert validate_remove_payload({"effect_id": "cap_abc"}) is None


def test_modify_validate_requires_id_and_override() -> None:
    from screen_recorder.agent.proposals import validate_modify_payload
    assert validate_modify_payload({}) is not None
    assert validate_modify_payload({"effect_id": "cap_abc"}) is not None, \
        "override 필드 0개면 거부"
    assert validate_modify_payload({"effect_id": "cap_abc", "text": "new"}) is None


def test_proposal_action_default() -> None:
    """기본 action 은 'add' — 기존 코드와의 호환성."""
    p = EffectProposal(type="caption", payload={"in_ms": 0, "out_ms": 1000, "text": "hi"})
    assert p.action == "add"


def test_proposal_action_remove() -> None:
    p = EffectProposal(action="remove", payload={"effect_id": "cap_xxx"})
    assert p.action == "remove"
    assert p.payload["effect_id"] == "cap_xxx"


# ============================================================
# 좌표 정합성 — Claude 가 정규화 좌표를 보내고, sidecar 까지 손상 없이 전달되는지.
# ============================================================
def test_arrow_pixel_coords_rejected() -> None:
    """Claude 가 픽셀 좌표(예: 160) 로 잘못 보내면 propose 시점에 거부.

    apply 시점 Point.__post_init__ 까지 가면 Claude 는 이미 'queued=true' 받고
    다음 단계 진행 → 사용자 혼란. 큐 적재 시점에 잡아야 함.
    """
    err = validate_payload("arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 160, "y": 90}, "end": {"x": 200, "y": 90},
    })
    assert err is not None, "픽셀 좌표는 거부되어야 함"
    assert "0~1" in err or "normalized" in err.lower()


def test_arrow_normalized_coords_pass() -> None:
    """0~1 정규화는 OK."""
    err = validate_payload("arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.25, "y": 0.5}, "end": {"x": 0.75, "y": 0.5},
    })
    assert err is None


def test_arrow_slightly_offscreen_coords_pass() -> None:
    """[-0.5, 1.5] 범위 — 화살표 한쪽 끝이 살짝 화면 밖이어도 허용."""
    err = validate_payload("arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": -0.2, "y": 0.5}, "end": {"x": 1.2, "y": 0.5},
    })
    assert err is None


def test_zoom_pixel_coords_rejected() -> None:
    err = validate_payload("zoom", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 100, "y": 50, "scale": 1.0},
        "end":   {"x": 100, "y": 50, "scale": 2.0},
    })
    assert err is not None
    assert "0~1" in err or "normalized" in err.lower()


def test_zoom_scale_out_of_range_rejected() -> None:
    err = validate_payload("zoom", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 100.0},  # 100배 줌 거부
    })
    assert err is not None
    assert "scale" in err


def test_coord_roundtrip_arrow_end_to_end() -> None:
    """propose 큐 → take_all → build → ArrowEffect.start.x 가 정확히 보존되는지.

    좌표 손실/변환 사고 회귀 보호. Claude 가 (0.327, 0.812) 보냈는데
    sidecar 에 (0.5, 0.5) 로 들어가는 사고 방지.
    """
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="arrow", payload={
        "in_ms": 1000, "out_ms": 3000,
        "start": {"x": 0.327, "y": 0.812},
        "end":   {"x": 0.673, "y": 0.188},
    }))
    items = q.take_all()
    assert len(items) == 1
    eff = build_effect_from_proposal(items[0])
    assert eff.type == "arrow"
    assert eff.in_ms == 1000 and eff.out_ms == 3000
    # 좌표는 손실 없이 그대로 (float 비교라 abs 차).
    assert abs(eff.start.x - 0.327) < 1e-9
    assert abs(eff.start.y - 0.812) < 1e-9
    assert abs(eff.end.x - 0.673) < 1e-9
    assert abs(eff.end.y - 0.188) < 1e-9


def test_coord_roundtrip_zoom_end_to_end() -> None:
    """zoom 의 start.cx / start.cy / scale 보존 검증."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="zoom", payload={
        "in_ms": 500, "out_ms": 2500,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.25, "y": 0.4, "scale": 2.5},
    }))
    items = q.take_all()
    eff = build_effect_from_proposal(items[0])
    assert eff.type == "zoom"
    assert abs(eff.start.cx - 0.5) < 1e-9
    assert abs(eff.start.cy - 0.5) < 1e-9
    assert abs(eff.start.scale - 1.0) < 1e-9
    assert abs(eff.end.cx - 0.25) < 1e-9
    assert abs(eff.end.cy - 0.4) < 1e-9
    assert abs(eff.end.scale - 2.5) < 1e-9


# ============================================================
# zoom mode / region / dest — 2026-05-13 사용자 보고.
# "줌은 화면 전체를 지정하고있어서 소용이 없어" — fit_screen 만 propose 가능했음.
# ============================================================
def test_zoom_magnify_region_payload_accepted() -> None:
    """magnify_region 모드 + region + dest 필드가 그대로 통과되는지."""
    err = validate_payload("zoom", {
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.1, "y": 0.1, "scale": 1.0},
        "end":   {"x": 0.1, "y": 0.1, "scale": 3.0},
        "mode": "magnify_region",
        "region_w": 0.15, "region_h": 0.10,
        "dest_cx": 0.75, "dest_cy": 0.25,
        "dest_w": 0.4, "dest_h": 0.3,
    })
    assert err is None


def test_zoom_mode_invalid_rejected() -> None:
    err = validate_payload("zoom", {
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 2.0},
        "mode": "wrong_mode",
    })
    assert err is not None
    assert "mode" in err


def test_zoom_region_out_of_range_rejected() -> None:
    err = validate_payload("zoom", {
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 2.0},
        "mode": "magnify_region",
        "region_w": 1.5,  # > 1.0
    })
    assert err is not None
    assert "region_w" in err


def test_zoom_magnify_region_build_roundtrip() -> None:
    """propose → build → ZoomEffect 에 mode / region / dest 전달되는지."""
    p = EffectProposal(type="zoom", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.1, "y": 0.1, "scale": 1.0},
        "end":   {"x": 0.1, "y": 0.1, "scale": 3.0},
        "mode": "magnify_region",
        "region_w": 0.15, "region_h": 0.10,
        "dest_cx": 0.75, "dest_cy": 0.25,
        "dest_w": 0.4, "dest_h": 0.3,
    })
    eff = build_effect_from_proposal(p)
    assert eff.type == "zoom"
    assert eff.mode == "magnify_region"
    assert abs(eff.region_w - 0.15) < 1e-9
    assert abs(eff.region_h - 0.10) < 1e-9
    assert abs(eff.dest_cx - 0.75) < 1e-9
    assert abs(eff.dest_cy - 0.25) < 1e-9
    assert abs(eff.dest_w - 0.4) < 1e-9
    assert abs(eff.dest_h - 0.3) < 1e-9


def test_zoom_mode_omitted_defaults_to_fit_screen() -> None:
    """mode 생략 시 ZoomEffect 기본값 fit_screen — 기존 호환."""
    p = EffectProposal(type="zoom", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end":   {"x": 0.5, "y": 0.5, "scale": 2.0},
    })
    eff = build_effect_from_proposal(p)
    assert eff.mode == "fit_screen"


# ============================================================
# modify proposal — nested dict coercion (2026-05-13 회귀).
# ============================================================
def test_modify_nested_dict_coerced_to_dataclass() -> None:
    """propose_modify_effect 가 caption.font 를 dict 로 보낼 때 dataclass 로 변환되어야.

    사용자 보고: "AI 가 작업 2번 하니까 플레이 화면에 효과들이 안 나옴".
    원인: dataclasses.replace 가 타입 검증 없이 {dict} 를 font 자리에 박아 paintEvent
    의 `c.font.family` 가 AttributeError. _effect_from_dict 거치게 강제.
    """
    from screen_recorder.agent.proposals import apply_modify_overrides
    from screen_recorder.effects.types.caption import CaptionEffect, Font

    original = CaptionEffect(
        in_ms=0, out_ms=1000, text="hello",
        font=Font(family="sans-serif", size=36, bold=False),
    )
    overrides = {"font": {"family": "Pretendard", "size": 48}}
    new_eff = apply_modify_overrides(original, overrides)

    # font 는 Font 인스턴스 (dict 아님) — paintEvent 에서 .family 접근 가능해야.
    assert isinstance(new_eff.font, Font), \
        f"font 가 dict 인 채로 박힘 — 회귀 발생. type={type(new_eff.font)}"
    assert new_eff.font.family == "Pretendard"
    assert new_eff.font.size == 48
    # 명시 안 한 필드는 보존 — partial merge.
    assert new_eff.font.bold is False


def test_modify_partial_nested_keeps_other_fields() -> None:
    """{font: {size: 48}} 만 보내면 family/bold 는 원본 유지."""
    from screen_recorder.agent.proposals import apply_modify_overrides
    from screen_recorder.effects.types.caption import CaptionEffect, Font

    original = CaptionEffect(
        in_ms=0, out_ms=1000, text="hello",
        font=Font(family="Pretendard", size=36, bold=True),
    )
    overrides = {"font": {"size": 48}}
    new_eff = apply_modify_overrides(original, overrides)
    assert new_eff.font.family == "Pretendard", "기존 family 가 보존되어야"
    assert new_eff.font.size == 48
    assert new_eff.font.bold is True, "기존 bold 가 보존되어야"


def test_modify_top_level_field_works() -> None:
    """top-level 필드 (예: text) 변경 — 기존 단순 replace 와 동일 동작."""
    from screen_recorder.agent.proposals import apply_modify_overrides
    from screen_recorder.effects.types.caption import CaptionEffect

    original = CaptionEffect(in_ms=0, out_ms=1000, text="hello")
    new_eff = apply_modify_overrides(original, {"text": "world"})
    assert new_eff.text == "world"
    assert new_eff.in_ms == 0   # 보존.


def test_modify_arrow_nested_start_coerced() -> None:
    """arrow.start={"x":0.5} partial — Point dataclass 로 변환."""
    from screen_recorder.agent.proposals import apply_modify_overrides
    from screen_recorder.effects.types.arrow import ArrowEffect, Point

    original = ArrowEffect(
        in_ms=0, out_ms=1000,
        start=Point(x=0.3, y=0.5), end=Point(x=0.7, y=0.5),
    )
    new_eff = apply_modify_overrides(original, {"start": {"x": 0.1}})
    assert isinstance(new_eff.start, Point)
    assert new_eff.start.x == 0.1
    assert new_eff.start.y == 0.5   # 보존.


def test_arrow_missing_point_rejected() -> None:
    err = validate_payload("arrow", {
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.5},   # y 누락
        "end":   {"x": 0.5, "y": 0.5},
    })
    assert err is not None
    assert "y" in err


# ============================================================
# Dedup — 2026-05-19 사용자 보고. Claude 가 같은 cut 효과를 3번 propose →
# 사이드카에 중복으로 박혀 의미 없는 노이즈. propose 시점에 차단.
# ============================================================
def test_is_duplicate_cut_same_range() -> None:
    """같은 in_ms/out_ms cut 은 큐 추가 전 dup 으로 인식."""
    q = ProposalQueue()
    p1 = EffectProposal(action="add", type="cut", payload={"in_ms": 1000, "out_ms": 2000})
    assert q.is_duplicate(p1) is False, "빈 큐엔 dup 없음"
    q.add(p1)
    p2 = EffectProposal(action="add", type="cut", payload={"in_ms": 1000, "out_ms": 2000})
    assert q.is_duplicate(p2) is True, "같은 범위 cut 은 dup"


def test_is_duplicate_cut_different_range_not_dup() -> None:
    """다른 in_ms/out_ms cut 은 dup 아님."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="cut", payload={"in_ms": 1000, "out_ms": 2000}))
    p2 = EffectProposal(action="add", type="cut", payload={"in_ms": 1500, "out_ms": 2500})
    assert q.is_duplicate(p2) is False


def test_is_duplicate_caption_same_range_same_text() -> None:
    """같은 in_ms/out_ms + 같은 text caption 은 dup (눈에 보이는 차이 0)."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="caption",
                          payload={"in_ms": 0, "out_ms": 1000, "text": "안녕"}))
    p2 = EffectProposal(action="add", type="caption",
                         payload={"in_ms": 0, "out_ms": 1000, "text": "안녕"})
    assert q.is_duplicate(p2) is True


def test_is_duplicate_caption_same_range_different_text_not_dup() -> None:
    """같은 범위 + 다른 text 는 dup 아님 (의도적 overlay 가능)."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="caption",
                          payload={"in_ms": 0, "out_ms": 1000, "text": "안녕"}))
    p2 = EffectProposal(action="add", type="caption",
                         payload={"in_ms": 0, "out_ms": 1000, "text": "다른 자막"})
    assert q.is_duplicate(p2) is False


def test_is_duplicate_speed_same_rate() -> None:
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="speed",
                          payload={"in_ms": 0, "out_ms": 2000, "rate": 2.0}))
    p2 = EffectProposal(action="add", type="speed",
                         payload={"in_ms": 0, "out_ms": 2000, "rate": 2.0})
    assert q.is_duplicate(p2) is True


def test_is_duplicate_speed_different_rate_not_dup() -> None:
    """같은 범위 + 다른 rate — conflict 일 수 있지만 dup 아님 (apply 가 처리)."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="speed",
                          payload={"in_ms": 0, "out_ms": 2000, "rate": 2.0}))
    p2 = EffectProposal(action="add", type="speed",
                         payload={"in_ms": 0, "out_ms": 2000, "rate": 0.5})
    assert q.is_duplicate(p2) is False


def test_is_duplicate_broll_same_src() -> None:
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="broll",
                          payload={"in_ms": 0, "out_ms": 5000, "src": "C:/a.mp4"}))
    p2 = EffectProposal(action="add", type="broll",
                         payload={"in_ms": 0, "out_ms": 5000, "src": "C:/a.mp4"})
    assert q.is_duplicate(p2) is True


def test_is_duplicate_broll_different_src_not_dup() -> None:
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="broll",
                          payload={"in_ms": 0, "out_ms": 5000, "src": "C:/a.mp4"}))
    p2 = EffectProposal(action="add", type="broll",
                         payload={"in_ms": 0, "out_ms": 5000, "src": "C:/b.mp4"})
    assert q.is_duplicate(p2) is False


def test_is_duplicate_zoom_not_deduped() -> None:
    """zoom 은 좌표/scale 미세 조정 가능성 — false positive 위험 → dedup 제외."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="zoom", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end": {"x": 0.5, "y": 0.5, "scale": 2.0},
    }))
    p2 = EffectProposal(action="add", type="zoom", payload={
        "in_ms": 0, "out_ms": 2000,
        "start": {"x": 0.5, "y": 0.5, "scale": 1.0},
        "end": {"x": 0.5, "y": 0.5, "scale": 2.0},
    })
    assert q.is_duplicate(p2) is False


def test_is_duplicate_arrow_not_deduped() -> None:
    """arrow 도 마찬가지 — 같은 위치 화살표 2개 의도 가능성 있음."""
    q = ProposalQueue()
    q.add(EffectProposal(action="add", type="arrow", payload={
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.3, "y": 0.5}, "end": {"x": 0.7, "y": 0.5},
    }))
    p2 = EffectProposal(action="add", type="arrow", payload={
        "in_ms": 0, "out_ms": 1000,
        "start": {"x": 0.3, "y": 0.5}, "end": {"x": 0.7, "y": 0.5},
    })
    assert q.is_duplicate(p2) is False


def test_is_duplicate_remove_action_never_dup() -> None:
    """remove proposal 은 dedup 대상 아님 — 같은 effect_id 2번 remove 하면 apply 시점 처리."""
    q = ProposalQueue()
    q.add(EffectProposal(action="remove", payload={"effect_id": "cap_x"}))
    p2 = EffectProposal(action="remove", payload={"effect_id": "cap_x"})
    assert q.is_duplicate(p2) is False


def test_is_duplicate_modify_action_never_dup() -> None:
    """modify proposal 도 dedup 안 함 — 같은 effect_id 다른 override 의도일 수 있음."""
    q = ProposalQueue()
    q.add(EffectProposal(action="modify", payload={"effect_id": "cap_x", "text": "a"}))
    p2 = EffectProposal(action="modify", payload={"effect_id": "cap_x", "text": "b"})
    assert q.is_duplicate(p2) is False
