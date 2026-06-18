"""효과 종류별 dataclass — caption/speed/zoom/broll/cut/arrow.

EFFECT_CLASSES 는 직렬화/역직렬화에서 type 문자열 → 클래스 매핑으로 쓰인다.
"""
from .caption import CaptionEffect
from .speed import SpeedEffect
from .zoom import ZoomEffect
from .broll import BrollEffect
from .cut import CutEffect
from .arrow import ArrowEffect
from .rect import RectEffect

EFFECT_CLASSES: dict[str, type] = {
    "caption": CaptionEffect,
    "speed": SpeedEffect,
    "zoom": ZoomEffect,
    "broll": BrollEffect,
    "cut": CutEffect,
    "arrow": ArrowEffect,
    "rect": RectEffect,
}


def effect_class_for(type_name: str) -> type:
    """type 문자열 → 효과 클래스. 없으면 KeyError."""
    cls = EFFECT_CLASSES.get(type_name)
    if cls is None:
        raise KeyError(f"unknown effect type {type_name!r}")
    return cls
