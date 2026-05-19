"""SpeedEffect — 구간 배속."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..model import Effect


_VALID_AUDIO = {"auto", "mute", "atempo"}


@dataclass(kw_only=True)
class SpeedEffect(Effect):
    type: Literal["speed"] = "speed"
    rate: float = 1.0
    audio: str = "auto"
    show_hud: bool = True
    hud_font_pt: int = 14

    def __post_init__(self) -> None:
        super().__post_init__()
        if not (0.1 <= self.rate <= 32.0):
            raise ValueError(f"rate must be in [0.1, 32.0], got {self.rate}")
        if self.audio not in _VALID_AUDIO:
            raise ValueError(
                f"audio must be one of {sorted(_VALID_AUDIO)}, got {self.audio!r}"
            )
