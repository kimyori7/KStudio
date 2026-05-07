"""CaptionEffect — 텍스트 오버레이."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from ..model import Effect


_VALID_ANCHORS = {
    "top-left", "top-center", "top-right",
    "middle-left", "middle-center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
    "free",  # offset_x/offset_y 가 0~1 정규화 좌표
}


@dataclass
class Font:
    family: str = "sans-serif"
    size: int = 36
    bold: bool = False

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError(f"font size must be > 0, got {self.size}")


@dataclass
class Stroke:
    color: str = "#000000"
    width: int = 0  # 0 = 외곽선 없음

    def __post_init__(self) -> None:
        if self.width < 0 or self.width > 6:
            raise ValueError(f"stroke width must be in [0, 6], got {self.width}")


@dataclass
class Background:
    color: str = "#000000"
    opacity: float = 0.5  # 0..1

    def __post_init__(self) -> None:
        if not (0.0 <= self.opacity <= 1.0):
            raise ValueError(f"opacity must be in [0, 1], got {self.opacity}")


@dataclass
class Position:
    anchor: str = "bottom-center"
    offset_x: float = 0.0
    offset_y: float = 0.0

    def __post_init__(self) -> None:
        if self.anchor not in _VALID_ANCHORS:
            raise ValueError(
                f"anchor must be one of {sorted(_VALID_ANCHORS)}, got {self.anchor!r}"
            )


@dataclass
class Fade:
    in_ms: int = 300
    out_ms: int = 300


@dataclass
class CaptionEffect(Effect):
    text: str = ""
    font: Font = field(default_factory=Font)
    fill: str = "#ffffff"
    stroke: Stroke | None = None
    shadow: bool = False
    background: Background | None = None
    position: Position = field(default_factory=Position)
    fade: Fade = field(default_factory=Fade)

    def __init__(
        self,
        in_ms: int,
        out_ms: int,
        text: str = "",
        font: Font | None = None,
        fill: str = "#ffffff",
        stroke: Stroke | None = None,
        shadow: bool = False,
        background: Background | None = None,
        position: Position | None = None,
        fade: Fade | None = None,
        id: str | None = None,
    ) -> None:
        self.type = "caption"
        self.in_ms = in_ms
        self.out_ms = out_ms
        self.text = text
        self.font = font if font is not None else Font()
        self.fill = fill
        self.stroke = stroke
        self.shadow = shadow
        self.background = background
        self.position = position if position is not None else Position()
        self.fade = fade if fade is not None else Fade()

        # Need to set id before calling parent validation
        if id is None:
            from ..model import _new_id
            self.id = _new_id()
        else:
            self.id = id

        # Call parent validation
        Effect.__post_init__(self)
