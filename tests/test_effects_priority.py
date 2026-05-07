"""효과 합성 우선순위 정렬."""
from screen_recorder.effects.priority import sort_for_render, RENDER_ORDER
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint
from screen_recorder.effects.types.broll import BrollEffect
from screen_recorder.effects.types.cut import CutEffect


def test_render_order_is_spec_defined():
    assert RENDER_ORDER == ["cut", "speed", "broll", "zoom", "caption"]


def test_sort_for_render_returns_in_order():
    items = [
        CaptionEffect(in_ms=0, out_ms=1000, text="x"),
        CutEffect(in_ms=2000, out_ms=3000),
        ZoomEffect(in_ms=4000, out_ms=5000,
                   start=ZoomPoint(), end=ZoomPoint(scale=2.0)),
        SpeedEffect(in_ms=6000, out_ms=7000, rate=2.0),
        BrollEffect(in_ms=8000, out_ms=9000, src="x.mp4", placement="fullscreen"),
    ]
    sorted_items = sort_for_render(items)
    types = [e.type for e in sorted_items]
    assert types == ["cut", "speed", "broll", "zoom", "caption"]


def test_sort_for_render_stable_within_same_type():
    """같은 type 끼리는 in_ms 오름차순."""
    items = [
        CaptionEffect(in_ms=5000, out_ms=6000, text="b"),
        CaptionEffect(in_ms=1000, out_ms=2000, text="a"),
        CaptionEffect(in_ms=3000, out_ms=4000, text="c"),
    ]
    sorted_items = sort_for_render(items)
    starts = [e.in_ms for e in sorted_items]
    assert starts == [1000, 3000, 5000]
