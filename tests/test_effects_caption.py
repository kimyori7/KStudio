"""CaptionEffect dataclass."""
import pytest
from screen_recorder.effects.types.caption import (
    CaptionEffect, Font, Stroke, Background, Position, Fade,
)


def test_caption_minimal_construct():
    c = CaptionEffect(in_ms=0, out_ms=1000, text="hi")
    assert c.type == "caption"
    assert c.text == "hi"
    # 기본값 확인 (2026-05-15 변경: 맑은 고딕 30 + 외곽선 검정 두께 2 기본)
    assert c.font.family == "맑은 고딕"
    assert c.font.size == 30
    assert c.fill == "#ffffff"
    assert isinstance(c.stroke, Stroke)
    assert c.stroke.color == "#000000"
    assert c.stroke.width == 2


def test_caption_full_construct():
    c = CaptionEffect(
        in_ms=1000, out_ms=4000, text="안녕",
        font=Font(family="Pretendard", size=48, bold=True),
        fill="#ff0000",
        stroke=Stroke(color="#000000", width=3),
        shadow=True,
        background=Background(color="#000000", opacity=0.5),
        position=Position(anchor="bottom-center", offset_x=0, offset_y=-40),
        fade=Fade(in_ms=300, out_ms=300),
    )
    assert c.font.family == "Pretendard"
    assert c.background.opacity == 0.5
    assert c.position.anchor == "bottom-center"


def test_caption_rejects_invalid_anchor():
    with pytest.raises(ValueError, match="anchor"):
        Position(anchor="middle-of-nowhere", offset_x=0, offset_y=0)


def test_caption_rejects_negative_font_size():
    with pytest.raises(ValueError, match="size"):
        Font(family="x", size=0, bold=False)


def test_caption_rejects_invalid_opacity():
    with pytest.raises(ValueError, match="opacity"):
        Background(color="#000", opacity=1.5)
    with pytest.raises(ValueError, match="opacity"):
        Background(color="#000", opacity=-0.1)
