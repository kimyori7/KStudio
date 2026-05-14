"""SYSTEM_PROMPT 회귀 보호 — 좌표 정확도 관련 핵심 지침이 빠지지 않게.

리팩토링/단축 시도 시 이 테스트가 빠진 항목을 잡아냄. 한 줄짜리 가벼운 검사들.

사용자 보고 (2026-05-13): "타이틀에 화살표" 요청 시 Claude 가 width=320 의 저해상도
프레임만 보고 좌표 추측 → 묘사("타이틀")와 실제 좌표(좌상단 빈 공간) 불일치. 시스템
프롬프트에 5단계 절차 + 고해상도 권장을 추가해 자기 검증 강제. 이 테스트는 그 절차
요소들이 살아있는지 확인.
"""
from __future__ import annotations

from screen_recorder.agent.runtime import SYSTEM_PROMPT


def test_prompt_mentions_normalized_coords() -> None:
    """좌표 정규화 0~1 명시 — 픽셀 사고 방지의 기본."""
    assert "0~1 정규화" in SYSTEM_PROMPT


def test_prompt_forbids_pixel_coords() -> None:
    """픽셀 값 금지 + 예시 — propose 거부 동작과 일치."""
    assert "절대 금지" in SYSTEM_PROMPT
    assert "x=160" in SYSTEM_PROMPT or "픽셀 단위 값" in SYSTEM_PROMPT


def test_prompt_requires_high_res_for_placement() -> None:
    """위치 결정용 width 권장 — 320 디폴트는 위치 정밀도 부족."""
    assert "width=960" in SYSTEM_PROMPT
    # 작은 객체엔 더 큰 width 안내도.
    assert "width=1280" in SYSTEM_PROMPT


def test_prompt_requires_verbal_grounding_before_coord() -> None:
    """좌표 계산 전에 픽셀 위치 *묘사* 강제 — hallucination 방지의 핵심."""
    assert "픽셀 위치" in SYSTEM_PROMPT
    # 묘사 예시 (특정 형식 강제는 아니지만 단계 명시).
    assert "한 줄로 명시" in SYSTEM_PROMPT or "묘사" in SYSTEM_PROMPT


def test_prompt_requires_self_verification_step() -> None:
    """단계 4 자기 검증 — 묘사와 계산값 모순 잡기."""
    assert "자기 검증" in SYSTEM_PROMPT
    assert "묘사" in SYSTEM_PROMPT and "좌표" in SYSTEM_PROMPT


def test_prompt_explains_normalization_math() -> None:
    """계산 공식 명시 — Claude 가 잘못 나누는 사고 방지."""
    assert "pixel_x / image_width" in SYSTEM_PROMPT
    assert "pixel_y / image_height" in SYSTEM_PROMPT


def test_prompt_mentions_modify_for_corrections() -> None:
    """사용자 보정 요청 패턴 안내 — '더 위로' 같은 자연어 → propose_modify_effect."""
    assert "propose_modify_effect" in SYSTEM_PROMPT
    assert "더 위로" in SYSTEM_PROMPT or "보정" in SYSTEM_PROMPT


def test_prompt_warns_strip_not_for_coords() -> None:
    """timeline_strip 좌표 결정 금지 — 합성 이미지라 어떤 썸네일 기준인지 모호."""
    assert "timeline_strip" in SYSTEM_PROMPT or "strip" in SYSTEM_PROMPT
    assert "gestalt" in SYSTEM_PROMPT


def test_prompt_proposal_pattern_described() -> None:
    """편집 = propose_* → list_proposals → apply 흐름이 살아있는지."""
    assert "propose_" in SYSTEM_PROMPT
    assert "apply_proposals" in SYSTEM_PROMPT


def test_prompt_step_ordering_intact() -> None:
    """5 단계 절차의 번호가 순서대로 존재 (1) ~ 5))."""
    for marker in ("1)", "2)", "3)", "4)", "5)"):
        assert marker in SYSTEM_PROMPT, f"단계 마커 {marker} 누락"


def test_prompt_forbids_skipping_steps() -> None:
    """단계 생략 금지 명시 — Claude 가 빠른 답 위해 단계 건너뛰는 경향 차단."""
    assert "생략하지 마세요" in SYSTEM_PROMPT or "생략" in SYSTEM_PROMPT


def test_prompt_mentions_preview_proposal() -> None:
    """preview_proposal 자기 검증 워크플로우 — apply 전 좌표 어긋남 잡기."""
    assert "preview_proposal" in SYSTEM_PROMPT
    assert "자기 검증" in SYSTEM_PROMPT


def test_prompt_forbids_hallucinating_effect_types() -> None:
    """효과 종류 추측 금지 — n_effects=2 만 보고 '컷 2개' 같은 hallucination 회귀 보호.

    2026-05-13 사용자 보고: 컷이 없는 영상에 대해 '효과 2개 (자르기)' 라고
    틀린 주장 후 '이미 2분으로 줄어있다' 까지 이어짐. 시스템 프롬프트가 이를
    명시적으로 차단해야.
    """
    assert "추측 금지" in SYSTEM_PROMPT
    assert "effects_by_type" in SYSTEM_PROMPT


def test_prompt_forbids_hallucinating_video_content() -> None:
    """영상 내용 묘사도 본 것만 — frame/strip/transcript 호출 없이는 금지."""
    has_anti = (
        "보지 않았으면 묘사 금지" in SYSTEM_PROMPT
        or ("영상" in SYSTEM_PROMPT and "보지 않았으면" in SYSTEM_PROMPT)
    )
    assert has_anti


def test_prompt_clarifies_zoom_start_coord_meaning() -> None:
    """zoom 의 start.x,y 가 scale=1 일 때도 의미 있음 — 보간 경로에 영향.

    에이전트가 "scale=1 이면 x,y 무시" 로 잘못 추측하던 케이스 회귀 보호.
    """
    assert "zoom" in SYSTEM_PROMPT
    # 보간 경로 / 카메라 중심점 / 단순 중앙 줌 예시 중 하나라도 있어야.
    has_clarification = (
        "보간" in SYSTEM_PROMPT
        or "카메라 중심" in SYSTEM_PROMPT
        or "단순 중앙 줌" in SYSTEM_PROMPT
    )
    assert has_clarification, "zoom start 좌표 의미 설명 누락"


def test_prompt_explains_zoom_two_modes() -> None:
    """zoom 의 fit_screen vs magnify_region 모드 차이가 설명되어야.

    2026-05-13 사용자 보고: "줌은 화면 전체를 지정하고있어서 소용이 없어".
    에이전트가 fit_screen (기본) 만 써서 작은 객체 강조에 부적합한 결과 반복.
    """
    assert "fit_screen" in SYSTEM_PROMPT
    assert "magnify_region" in SYSTEM_PROMPT


def test_prompt_guides_magnify_region_for_small_objects() -> None:
    """버튼·아이콘·작은 UI 강조 = magnify_region 으로 라우팅하도록 명시.

    이 가이드 없으면 에이전트가 다시 fit_screen 으로 화면 전체를 확대하는 사고 반복.
    """
    # '버튼' 또는 '아이콘' 키워드 + magnify_region 매핑이 같은 prompt 안에 존재.
    has_routing = (
        ("버튼" in SYSTEM_PROMPT or "아이콘" in SYSTEM_PROMPT or "작은 객체" in SYSTEM_PROMPT)
        and "magnify_region" in SYSTEM_PROMPT
    )
    assert has_routing, "magnify_region 선택 가이드 누락"


def test_prompt_distinguishes_three_durations() -> None:
    """source_duration_ms / duration_ms (편집 타임라인) / export_duration_ms 셋 모두 언급.

    2026-05-14 사용자 보고: 에이전트가 길이를 어떻게 정의해야 하는지 헷갈려해서
    "duration_ms = cut 후 결합 길이" 라는 *잘못된* 단순화로 환각 오해 일으킴.
    KStudio 의 진짜 동작: cut 은 편집 타임라인에 즉시 적용 안 됨 → duration_ms = source.
    export_duration_ms 가 cut 적용된 *예상* 출력 길이.
    """
    assert "source_duration_ms" in SYSTEM_PROMPT
    assert "duration_ms" in SYSTEM_PROMPT
    assert "export_duration_ms" in SYSTEM_PROMPT
    # KStudio cut 동작에 대한 명시적 설명 — '즉시 적용 안 됨' 또는 '편집 타임라인' 키워드.
    has_kstudio_behavior = (
        "즉시 적용" in SYSTEM_PROMPT
        or "편집 타임라인" in SYSTEM_PROMPT
        or "export 시점" in SYSTEM_PROMPT
    )
    assert has_kstudio_behavior
