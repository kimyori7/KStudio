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

    def __post_init__(self) -> None:
        if self.corner not in _VALID_CORNER:
            raise ValueError(
                f"corner must be one of {sorted(_VALID_CORNER)}, got {self.corner!r}"
            )
        if not (0.1 <= self.size_ratio <= 0.5):
            raise ValueError(
                f"size_ratio must be in [0.1, 0.5], got {self.size_ratio}"
            )


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
