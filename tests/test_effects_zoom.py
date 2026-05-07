"""ZoomEffect dataclass."""
import pytest
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint


def test_zoom_minimal_construct():
    z = ZoomEffect(
        in_ms=0, out_ms=3000,
        start=ZoomPoint(cx=0.5, cy=0.5, scale=1.0),
        end=ZoomPoint(cx=0.3, cy=0.4, scale=2.5),
    )
    assert z.type == "zoom"
    assert z.start.scale == 1.0
    assert z.end.scale == 2.5
    assert z.in_anim_ms == 300
    assert z.out_anim_ms == 300
    assert z.ease == "in-out"


def test_zoom_rejects_out_of_range_coord():
    with pytest.raises(ValueError, match="cx"):
        ZoomPoint(cx=1.1, cy=0.5, scale=1.0)
    with pytest.raises(ValueError, match="cy"):
        ZoomPoint(cx=0.5, cy=-0.1, scale=1.0)


def test_zoom_rejects_invalid_scale():
    with pytest.raises(ValueError, match="scale"):
        ZoomPoint(cx=0.5, cy=0.5, scale=0.0)
    with pytest.raises(ValueError, match="scale"):
        ZoomPoint(cx=0.5, cy=0.5, scale=11.0)  # > 10 상한


def test_zoom_rejects_invalid_ease():
    with pytest.raises(ValueError, match="ease"):
        ZoomEffect(
            in_ms=0, out_ms=3000,
            start=ZoomPoint(cx=0.5, cy=0.5, scale=1.0),
            end=ZoomPoint(cx=0.3, cy=0.3, scale=2.0),
            ease="warp-speed",
        )
