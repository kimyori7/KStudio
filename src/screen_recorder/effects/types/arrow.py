"""ArrowEffect — 캡션 패턴의 화살표 overlay 효과.

start/end 점은 정규화 (0~1) 좌표 — 영상 frame 안에서 비율 기반 위치. preview/export
사이 surface 크기 차이에도 같은 상대 위치 유지.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from ..model import Effect


@dataclass
class Point:
    x: float = 0.5
    y: float = 0.5

    def __post_init__(self) -> None:
        if not (-0.5 <= self.x <= 1.5):
            raise ValueError(f"x must be in [-0.5, 1.5], got {self.x}")
        if not (-0.5 <= self.y <= 1.5):
            raise ValueError(f"y must be in [-0.5, 1.5], got {self.y}")


@dataclass
class Fade:
    in_ms: int = 300
    out_ms: int = 300


@dataclass(kw_only=True)
class ArrowEffect(Effect):
    """직선 화살표 — start 에서 end 로. arrowhead 는 end 쪽."""
    type: Literal["arrow"] = "arrow"
    start: Point = field(default_factory=lambda: Point(x=0.3, y=0.5))
    end: Point = field(default_factory=lambda: Point(x=0.7, y=0.5))
    color: str = "#ff4040"
    thickness: int = 6   # source 픽셀 단위
    # 화살촉(머리) 크기 배율. 1.0 = 기존 (길이 thickness×3, 너비 thickness×1.4).
    # 굵기와 독립 — 얇은 선에 큰 머리, 굵은 선에 작은 머리도 가능.
    head_scale: float = 1.0
    fade: Fade = field(default_factory=Fade)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (1 <= self.thickness <= 64):
            raise ValueError(f"thickness must be in [1, 64], got {self.thickness}")
        if not (0.1 <= self.head_scale <= 8.0):
            raise ValueError(f"head_scale must be in [0.1, 8.0], got {self.head_scale}")
