"""effect_lanes_widget — cut 효과가 들어 있으면 CutLane 으로 자동 생성."""
from screen_recorder.effects import Sidecar
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.ui.video.cut_lane import CutLane
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def test_cut_effect_creates_cut_lane(qtbot):
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(effects=[CutEffect(in_ms=1000, out_ms=2000)])
    w.set_sidecar(sc)
    lane = w.lane_for_type("cut")
    assert lane is not None
    assert isinstance(lane, CutLane)


def test_cut_lane_receives_effects(qtbot):
    w = EffectLanesWidget()
    w.set_duration_ms(10000)
    qtbot.addWidget(w)
    e1 = CutEffect(in_ms=1000, out_ms=2000)
    e2 = CutEffect(in_ms=3000, out_ms=3000, src="x.mp4")  # splice
    sc = Sidecar(effects=[e1, e2])
    w.set_sidecar(sc)
    lane = w.lane_for_type("cut")
    assert len(lane.effects()) == 2
