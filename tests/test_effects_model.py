"""effects 패키지 import smoke."""

import pytest
from screen_recorder.effects.model import Effect, EffectList


def test_effects_package_importable():
    import screen_recorder.effects  # noqa
    import screen_recorder.effects.types  # noqa


def test_effect_auto_generates_id():
    e1 = Effect(type="caption", in_ms=0, out_ms=1000)
    e2 = Effect(type="caption", in_ms=0, out_ms=1000)
    assert e1.id != e2.id
    assert isinstance(e1.id, str) and len(e1.id) == 36  # UUID4 hex with dashes


def test_effect_explicit_id_preserved():
    e = Effect(id="fixed-id", type="caption", in_ms=0, out_ms=1000)
    assert e.id == "fixed-id"


def test_effect_rejects_negative_in_ms():
    with pytest.raises(ValueError, match="in_ms"):
        Effect(type="caption", in_ms=-1, out_ms=100)


def test_effect_rejects_out_ms_le_in_ms():
    with pytest.raises(ValueError, match="out_ms"):
        Effect(type="caption", in_ms=100, out_ms=100)
    with pytest.raises(ValueError, match="out_ms"):
        Effect(type="caption", in_ms=100, out_ms=50)


def test_effect_duration_ms():
    e = Effect(type="caption", in_ms=1000, out_ms=4000)
    assert e.duration_ms == 3000


def test_effect_list_sorted_by_in_ms():
    lst = EffectList()
    lst.append(Effect(type="caption", in_ms=2000, out_ms=3000))
    lst.append(Effect(type="caption", in_ms=500, out_ms=1500))
    lst.append(Effect(type="caption", in_ms=4000, out_ms=5000))
    starts = [e.in_ms for e in lst.sorted_by_time()]
    assert starts == [500, 2000, 4000]


def test_effect_list_filter_by_type():
    lst = EffectList()
    lst.append(Effect(type="caption", in_ms=0, out_ms=1000))
    lst.append(Effect(type="speed", in_ms=2000, out_ms=3000))
    lst.append(Effect(type="caption", in_ms=4000, out_ms=5000))
    captions = lst.of_type("caption")
    assert len(captions) == 2
    assert all(e.type == "caption" for e in captions)


def test_package_reexports_main_symbols():
    from screen_recorder.effects import (
        Effect, EffectList,
        Sidecar, Trim, save_atomic, load,
        SidecarStore, compute_video_hash, default_sidecar_dir,
        History,
        sort_for_render, RENDER_ORDER,
        overlaps_existing,
        EFFECT_CLASSES, effect_class_for,
    )
    # 모두 callable 또는 클래스
    for sym in (Effect, EffectList, Sidecar, History, SidecarStore):
        assert isinstance(sym, type)
