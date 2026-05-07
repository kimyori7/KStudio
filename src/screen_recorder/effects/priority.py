"""효과 합성 우선순위 — 시간축 변형 → 공간 변환 → 오버레이 순서."""
from __future__ import annotations
from typing import Iterable

from .model import Effect


# Spec: 시간축 효과(cut → speed → broll) 가 먼저, 그 위에 공간(zoom),
# 마지막에 오버레이(caption). HUD 는 SpeedEffect 의 일부이므로
# export 단계에서 caption 보다 더 위에 그려진다.
RENDER_ORDER: list[str] = ["cut", "speed", "broll", "zoom", "caption"]


def sort_for_render(effects: Iterable[Effect]) -> list[Effect]:
    """RENDER_ORDER 우선, 같은 type 끼리는 in_ms 오름차순."""
    rank = {t: i for i, t in enumerate(RENDER_ORDER)}
    return sorted(effects, key=lambda e: (rank.get(e.type, 999), e.in_ms))
