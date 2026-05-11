"""effect_lanes_widget — cut 효과가 들어 있으면 CutLane 으로 자동 생성. (obsolete)"""
import pytest

pytestmark = pytest.mark.skip(
    reason="Stage D (2026-05-08): cut lane 은 segment 트랙으로 흡수되어 제거. "
           "자르기는 트랙 lane 의 우클릭 메뉴 또는 단축키 S 로."
)


def test_cut_effect_creates_cut_lane():
    pass


def test_cut_lane_receives_effects():
    pass
