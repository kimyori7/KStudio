"""ZoomEffect — 구간 줌."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from ..model import Effect


_VALID_EASE = {"linear", "in", "out", "in-out"}
_VALID_MODE = {"fit_screen", "magnify_region"}


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
    # Phase 24: 줌 모드
    # - "fit_screen" (기본): 기존 동작 — (cx, cy) 주위의 1/scale 영역을 전체 화면으로 stretch.
    # - "magnify_region": 부분 영역만 N배 확대 — 나머지 원본 그대로 표시.
    mode: str = "fit_screen"
    # magnify_region 모드의 source(원본) 영역 크기 (정규화 0~1). fit_screen 에선 무시.
    region_w: float = 0.3
    region_h: float = 0.3
    # Phase 27 — magnify_region 의 dest(확대 후 표시) rect 를 source 와 분리.
    # 중심 좌표 (정규화). 기본값은 source 와 같은 중심.
    dest_cx: float = 0.5
    dest_cy: float = 0.5
    # 크기 (정규화). 기본값은 source × start.scale — 인스펙터/preview 가 새 ZoomEffect
    # 생성 시 자동 채워 넣음. None 으로 두면 set_effect/마이그레이션에서 보정.
    dest_w: float = 0.6
    dest_h: float = 0.6

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.ease not in _VALID_EASE:
            raise ValueError(
                f"ease must be one of {sorted(_VALID_EASE)}, got {self.ease!r}"
            )
        if self.mode not in _VALID_MODE:
            raise ValueError(
                f"mode must be one of {sorted(_VALID_MODE)}, got {self.mode!r}"
            )
        if not (0.05 <= self.region_w <= 1.0):
            raise ValueError(f"region_w must be in [0.05, 1.0], got {self.region_w}")
        if not (0.05 <= self.region_h <= 1.0):
            raise ValueError(f"region_h must be in [0.05, 1.0], got {self.region_h}")
        if not (0.0 <= self.dest_cx <= 1.0):
            raise ValueError(f"dest_cx must be in [0, 1], got {self.dest_cx}")
        if not (0.0 <= self.dest_cy <= 1.0):
            raise ValueError(f"dest_cy must be in [0, 1], got {self.dest_cy}")
        if not (0.05 <= self.dest_w <= 2.0):
            raise ValueError(f"dest_w must be in [0.05, 2.0], got {self.dest_w}")
        if not (0.05 <= self.dest_h <= 2.0):
            raise ValueError(f"dest_h must be in [0.05, 2.0], got {self.dest_h}")
