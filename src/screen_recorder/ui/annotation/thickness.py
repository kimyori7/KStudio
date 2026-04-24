"""주석 선 두께 단계 ↔ 픽셀 매핑."""
from __future__ import annotations

THICKNESS_STEPS: tuple[int, int, int, int] = (1, 2, 3, 4)
DEFAULT_THICKNESS_STEP: int = 2

_PIXEL_MAP: dict[int, int] = {1: 2, 2: 4, 3: 6, 4: 8}


def thickness_to_pixels(step: int) -> int:
    """두께 단계(1~4)를 실제 선 굵기 픽셀로 변환."""
    if step not in _PIXEL_MAP:
        raise ValueError(f"thickness step must be 1..4, got {step}")
    return _PIXEL_MAP[step]
