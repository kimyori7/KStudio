import pytest
from screen_recorder.ui.annotation.thickness import (
    thickness_to_pixels,
    THICKNESS_STEPS,
    DEFAULT_THICKNESS_STEP,
)


def test_thickness_steps_are_four():
    assert len(THICKNESS_STEPS) == 4
    assert THICKNESS_STEPS == (1, 2, 3, 4)


def test_default_is_step_2():
    assert DEFAULT_THICKNESS_STEP == 2


@pytest.mark.parametrize("step,px", [(1, 2), (2, 4), (3, 6), (4, 8)])
def test_mapping(step, px):
    assert thickness_to_pixels(step) == px


def test_out_of_range_raises():
    with pytest.raises(ValueError):
        thickness_to_pixels(0)
    with pytest.raises(ValueError):
        thickness_to_pixels(5)
