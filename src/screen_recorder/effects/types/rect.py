"""RectEffect — 테두리 사각형 overlay 효과 (화살표 패턴).

start/end 는 정규화 (0~1) 좌표의 대각 두 모서리. 그리기·hit-test 시 두 점의
min/max 로 사각형을 만든다(모서리를 반대편 너머로 끌어도 비반전). 테두리만 — 채움 없음.
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
class RectEffect(Effect):
    """테두리 사각형 — start/end 는 대각 두 모서리. 테두리만(채움 없음)."""
    type: Literal["rect"] = "rect"
    start: Point = field(default_factory=lambda: Point(x=0.3, y=0.4))
    end: Point = field(default_factory=lambda: Point(x=0.7, y=0.6))
    color: str = "#ff4040"
    thickness: int = 4   # 테두리 굵기, source 픽셀 단위
    fade: Fade = field(default_factory=Fade)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (1 <= self.thickness <= 64):
            raise ValueError(f"thickness must be in [1, 64], got {self.thickness}")
