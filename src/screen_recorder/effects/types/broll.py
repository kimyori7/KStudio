"""BrollEffect — 영상 사이에 다른 영상/이미지/GIF 끼워넣기."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..model import Effect


_VALID_PLACEMENT = {"fullscreen", "pip"}
_VALID_AUDIO_MIX = {"original_only", "broll_only", "both", "mute"}
_VALID_CORNER = {"top-left", "top-right", "bottom-left", "bottom-right"}


@dataclass
class PipConfig:
    corner: str = "bottom-right"
    size_ratio: float = 0.3   # 영상 너비 대비 (0.1 ~ 0.5)
    # pos_x / pos_y 가 둘 다 None 이 아니면 corner 보다 우선해 자유 위치로 그린다.
    # 좌표는 PiP 사각형의 좌상단을 기준으로 한 정규화 (0~1) 좌표 — 영상 안에서만 의미.
    # 드래그로 설정. corner 는 처음 추가 시 기본값으로만 쓰이고 자유 위치 후엔 무시된다.
    pos_x: float | None = None
    pos_y: float | None = None

    def __post_init__(self) -> None:
        if self.corner not in _VALID_CORNER:
            raise ValueError(
                f"corner must be one of {sorted(_VALID_CORNER)}, got {self.corner!r}"
            )
        if not (0.1 <= self.size_ratio <= 0.5):
            raise ValueError(
                f"size_ratio must be in [0.1, 0.5], got {self.size_ratio}"
            )
        for name, v in (("pos_x", self.pos_x), ("pos_y", self.pos_y)):
            if v is None:
                continue
            if not (0.0 <= float(v) <= 1.0):
                raise ValueError(f"{name} must be in [0, 1], got {v}")


@dataclass(kw_only=True)
class BrollEffect(Effect):
    type: Literal["broll"] = "broll"
    src: str = ""                       # 영상/이미지/GIF 경로
    placement: str = "fullscreen"       # fullscreen | pip
    pip: PipConfig | None = None        # placement="pip" 일 때만
    audio_mix: str = "both"             # original_only | broll_only | both | mute
    audio_balance: float = 0.5          # both 일 때 원본 비율 (0.0 ~ 1.0)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.placement not in _VALID_PLACEMENT:
            raise ValueError(
                f"placement must be one of {sorted(_VALID_PLACEMENT)}, got {self.placement!r}"
            )
        if self.audio_mix not in _VALID_AUDIO_MIX:
            raise ValueError(
                f"audio_mix must be one of {sorted(_VALID_AUDIO_MIX)}, got {self.audio_mix!r}"
            )
        if not (0.0 <= self.audio_balance <= 1.0):
            raise ValueError(
                f"audio_balance must be in [0, 1], got {self.audio_balance}"
            )
