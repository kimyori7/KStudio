"""ZoomEffect — 구간 줌."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from ..model import Effect


_VALID_EASE = {"linear", "in", "out", "in-out"}


@dataclass
class ZoomPoint:
    """줌 위치 + 배율 (정규화 좌표)."""
    cx: float = 0.5
    cy: float = 0.5
    scale: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.cx <= 1.0):
            raise ValueError(f"cx must be in [0, 1], got {self.cx}")
        if not (0.0 <= self.cy <= 1.0):
            raise ValueError(f"cy must be in [0, 1], got {self.cy}")
        if not (0.1 <= self.scale <= 10.0):
            raise ValueError(f"scale must be in [0.1, 10.0], got {self.scale}")


@dataclass(kw_only=True)
class ZoomEffect(Effect):
    type: Literal["zoom"] = "zoom"
    start: ZoomPoint = field(default_factory=ZoomPoint)
    end: ZoomPoint = field(default_factory=ZoomPoint)
    ease: str = "in-out"
    in_anim_ms: int = 300
    out_anim_ms: int = 300
    # 인스펙터의 "미리보기" 체크박스 — True 이면 이 zoom 구간 재생 시 화면이 실제로
    # 줌인 (export 결과와 동일한 효과). False 이면 화면은 그대로, 미리보기 가이드 박스만
    # PreviewOverlay 가 그림. 사이드카에 저장되며 새로 만든 ZoomEffect 의 기본값은 False.
    preview: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.ease not in _VALID_EASE:
            raise ValueError(
                f"ease must be one of {sorted(_VALID_EASE)}, got {self.ease!r}"
            )
