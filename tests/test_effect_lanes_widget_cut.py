"""effect_lanes_widget — cut 효과 회귀 보호.

History:
- Stage D (2026-05-08): cut lane 을 segment 트랙으로 흡수하려 했으나 video_track_lane 에
  cut 표시 코드 미구현 → cut 효과가 화면에 안 보이는 회귀 (사용자 보고 2026-05-19).
- 2026-05-19 fix: _LANE_ORDER 에 cut 복구. 이 테스트는 그 회귀가 다시 안 나오게 보호.

video_track_lane 에 cut 흡수가 완성되면 _LANE_ORDER 에서 cut 제거 + 이 테스트 obsolete.
"""
from screen_recorder.effects.sidecar import Sidecar, Trim
from screen_recorder.effects.types.cut import CutEffect
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.cut_lane import CutLane
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def test_cut_effect_creates_cut_lane(qtbot):
    """CutEffect 1 개 → cut lane 1 개 표시 (CutLane 인스턴스)."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CutEffect(in_ms=1000, out_ms=2000)],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 1
    assert w.has_lane_for_type("cut") is True
    lane = w.lane_for_type("cut")
    assert isinstance(lane, CutLane)


def test_cut_lane_receives_effects(qtbot):
    """사이드카의 cut 효과들이 lane.effects() 로 모두 전달."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=20_000),
        effects=[
            CutEffect(in_ms=1000, out_ms=2000),
            CutEffect(in_ms=5000, out_ms=6000),
            CutEffect(in_ms=10_000, out_ms=11_000),
        ],
    )
    w.set_sidecar(sc)
    lane = w.lane_for_type("cut")
    effs = lane.effects()
    assert len(effs) == 3
    assert {e.in_ms for e in effs} == {1000, 5000, 10_000}


def test_cut_and_caption_both_show(qtbot):
    """사용자 시나리오 — Claude 가 cut 5 + caption 26 추가했을 때 둘 다 보이는지.

    2026-05-19 회귀 사용자 보고: cut 만 안 보임 (Stage D 미완성 부작용). caption 은
    원래 보였어야 하는데 사용자가 "둘 다 안 보임" 으로 보고. 둘 다 lane 만들어지는지 확인.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=120_000),
        effects=[
            CutEffect(in_ms=104_280, out_ms=105_240),
            CutEffect(in_ms=115_780, out_ms=116_230),
            CaptionEffect(in_ms=0, out_ms=6520, text="시작 자막"),
            CaptionEffect(in_ms=6520, out_ms=11_360, text="다음 자막"),
        ],
    )
    w.set_sidecar(sc)
    assert w.has_lane_for_type("cut") is True
    assert w.has_lane_for_type("caption") is True
    assert len(w.lane_for_type("cut").effects()) == 2
    assert len(w.lane_for_type("caption").effects()) == 2
