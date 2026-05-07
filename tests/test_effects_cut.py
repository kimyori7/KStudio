"""CutEffect dataclass."""
from screen_recorder.effects.types.cut import CutEffect


def test_cut_minimal_construct():
    c = CutEffect(in_ms=10000, out_ms=12000)
    assert c.type == "cut"
    assert c.duration_ms == 2000


def test_cut_inherits_id_validation():
    import pytest
    with pytest.raises(ValueError, match="out_ms"):
        CutEffect(in_ms=100, out_ms=100)
