"""EffectLanesWidget — lane 컨테이너 + 자동 생성."""
import pytest
from PySide6.QtCore import Qt

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video.effect_lanes_widget import EffectLanesWidget


def test_empty_sidecar_shows_no_lanes(qtbot):
    """Phase 24: 효과 0 개면 lane 없음 (이전엔 5 종 영구 표시). + 추가 버튼만 보임."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000))
    w.set_sidecar(sc)
    assert w.lane_count() == 0
    for t in ("caption", "speed", "zoom", "broll", "arrow"):
        assert w.has_lane_for_type(t) is False


def test_one_caption_shows_only_caption_lane(qtbot):
    """Phase 24: CaptionEffect 1 개 → caption lane 만 표시 (1 개)."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=1000, out_ms=4000, text="hi")],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 1
    assert w.has_lane_for_type("caption") is True
    assert len(w.lane_for_type("caption").effects()) == 1


def test_mixed_types_show_only_used_lanes(qtbot):
    """Phase 24: 캡션 2 + 배속 1 → caption + speed lane (2 개)만 표시."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[
            CaptionEffect(in_ms=1000, out_ms=4000, text="a"),
            CaptionEffect(in_ms=5000, out_ms=8000, text="b"),
            SpeedEffect(in_ms=2000, out_ms=3000, rate=2.0),
        ],
    )
    w.set_sidecar(sc)
    assert w.lane_count() == 2
    assert len(w.lane_for_type("caption").effects()) == 2
    assert len(w.lane_for_type("speed").effects()) == 1
    assert w.has_lane_for_type("zoom") is False


def test_set_sidecar_swaps_lanes_to_match_effects(qtbot):
    """Phase 24: 다른 사이드카로 교체 → 사용 안 하는 type 의 lane 은 제거, 필요한 type 만 표시."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc1 = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    sc2 = Sidecar(source_path="y", source_hash="h2", trim=Trim(in_ms=0, out_ms=10_000),
                  effects=[SpeedEffect(in_ms=0, out_ms=1000, rate=2.0)])
    w.set_sidecar(sc1)
    assert w.has_lane_for_type("caption") is True
    assert w.has_lane_for_type("speed") is False
    w.set_sidecar(sc2)
    assert w.has_lane_for_type("caption") is False
    assert w.has_lane_for_type("speed") is True
    assert len(w.lane_for_type("speed").effects()) == 1


def test_set_duration_propagates_to_lanes(qtbot):
    """set_duration_ms 가 모든 lane 에 전파."""
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    w.set_sidecar(sc)
    w.set_duration_ms(20_000)
    lane = w.lane_for_type("caption")
    assert lane.duration_ms() == 20_000


def test_lane_persists_when_all_effects_removed(qtbot):
    """효과 다 지워도 lane 자체는 유지 (사용자 요청 2026-05-13).

    이전 동작: 효과 0 → set_sidecar 가 lane 자동 제거 → 사용자가 "라인까지 사라짐" 으로 인지.
    새 동작: 같은 영상(source_hash 동일) 안에서는 효과 0 이라도 lane 보존. 사용자가
    명시적으로 "이 라인 지우기" 메뉴 사용해야만 제거.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc_with = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")],
    )
    sc_without = Sidecar(
        source_path="x", source_hash="h",   # 같은 영상.
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[],
    )
    w.set_sidecar(sc_with)
    assert w.has_lane_for_type("caption") is True
    # 효과 전부 삭제.
    w.set_sidecar(sc_without)
    # lane 은 유지 (효과 0 이지만).
    assert w.has_lane_for_type("caption") is True
    assert len(w.lane_for_type("caption").effects()) == 0


def test_lane_reset_on_video_switch(qtbot):
    """다른 영상 (source_hash 변경) 으로 전환 시 lane 전부 리셋.

    효과 다 지웠을 때 lane 유지 정책이 영상 전환에도 적용되면 이전 영상의 lane 이
    남는 누수 발생. source_hash 비교로 영상 경계 명확.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc_video_a = Sidecar(
        source_path="a", source_hash="ha",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")],
    )
    sc_video_b_empty = Sidecar(
        source_path="b", source_hash="hb",   # *다른* 영상.
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[],
    )
    w.set_sidecar(sc_video_a)
    assert w.has_lane_for_type("caption") is True
    w.set_sidecar(sc_video_b_empty)
    # 다른 영상이라 caption lane 도 사라져야.
    assert w.has_lane_for_type("caption") is False
    assert w.lane_count() == 0


def test_explicit_remove_lane_still_works(qtbot):
    """우클릭 "이 라인 지우기" 는 여전히 lane 제거해야 한다.

    auto-removal 비활성화돼도 사용자가 명시 메뉴로 lane 지우는 길은 보장.
    pending_removal set 으로 marking → 다음 set_sidecar 에서 제거.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc_with = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")],
    )
    w.set_sidecar(sc_with)
    assert w.has_lane_for_type("caption") is True

    # "이 라인 지우기" 메뉴 호출 시뮬레이션 — 모든 효과가 효과_deleted emit.
    w._on_remove_lane_requested("caption", track_idx=0)
    # pending_removal 에 등록됨.
    assert "caption" in w._lanes_pending_removal

    # controller 가 효과 삭제 후 새 sidecar 로 set_sidecar — pending 처리됨.
    sc_after = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[],
    )
    w.set_sidecar(sc_after)
    assert w.has_lane_for_type("caption") is False, \
        "명시 이 라인 지우기 후엔 lane 사라져야"


def test_remove_lane_survives_intermediate_sidecar(qtbot):
    """이 라인 지우기 후 intermediate set_sidecar (caption 아직 있음) 가 들어와도
    lane 이 최종적으로 사라져야 한다.

    회귀 (2026-05-13: "캡션 라인 지우기 누르면 캡션만 날아가고 라인만 남아있지"):
    pending_removal 처리가 lane 생성 *전* 이었던 시절, intermediate set_sidecar 가
    caption 갖고 들어오면:
    1. pending_removal 처리 → lane pop, pending_removal 비움
    2. types_in_use 에 'caption' 있음 → 다시 lane 생성
    3. 최종 set_sidecar (caption 0) 도착 → pending_removal 비어있어 처리 X → lane 유지

    Fix: pending_removal 처리를 lane 생성/효과 적용 *후* 로. effects()==[] 일 때만 제거.
    """
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    cap = CaptionEffect(in_ms=0, out_ms=1000, text="a")
    sc_with = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[cap],
    )
    w.set_sidecar(sc_with)
    assert w.has_lane_for_type("caption") is True

    # "이 라인 지우기" — pending_removal 에 등록 + effect_deleted emit.
    w._on_remove_lane_requested("caption", track_idx=0)
    assert "caption" in w._lanes_pending_removal

    # 중간 set_sidecar — controller 가 아직 caption 안 지운 시점에 들어옴.
    w.set_sidecar(sc_with)
    # 이 시점엔 lane 유지 (효과 있으니). pending_removal 도 유지.
    assert w.has_lane_for_type("caption") is True
    assert "caption" in w._lanes_pending_removal

    # 최종 set_sidecar — controller 가 caption 지움.
    sc_after = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[],
    )
    w.set_sidecar(sc_after)
    # 이제 lane 제거 — effects()==[] 이고 pending_removal 에 등록돼있으므로.
    assert w.has_lane_for_type("caption") is False, \
        "intermediate sidecar 후에도 lane 이 최종 제거되어야 — 회귀 발생"


def test_explicit_remove_lane_keeps_other_tracks(qtbot):
    """track 0 에 화살표 1, track 1 에 화살표 1 — track 0 우클릭 '이 라인 지우기' 하면
    track 0 효과만 삭제, lane 자체는 유지 (track 1 효과 있으므로).
    """
    from screen_recorder.effects.types.arrow import ArrowEffect

    w = EffectLanesWidget()
    qtbot.addWidget(w)
    arr0 = ArrowEffect(in_ms=0, out_ms=1000, track_idx=0)
    arr1 = ArrowEffect(in_ms=2000, out_ms=3000, track_idx=1)
    sc = Sidecar(
        source_path="x", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[arr0, arr1],
    )
    w.set_sidecar(sc)
    assert w.has_lane_for_type("arrow") is True

    w._on_remove_lane_requested("arrow", track_idx=0)
    # track_idx=1 효과 남아있으므로 lane 제거 예약 *안* 됨.
    assert "arrow" not in w._lanes_pending_removal


def test_caption_type_uses_caption_lane_class(qtbot):
    """type='caption' lane 은 CaptionLane 인스턴스여야 (Task 3 에서 도입)."""
    # CaptionLane 미도입 시점엔 base EffectLane 으로 fallback. Task 3 commit 후
    # 이 테스트는 CaptionLane import 가 가능해진다.
    w = EffectLanesWidget()
    qtbot.addWidget(w)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=0, out_ms=1000, text="a")])
    w.set_sidecar(sc)
    lane = w.lane_for_type("caption")
    assert lane is not None
    # Stage 3 Task 3 후엔 CaptionLane 의 인스턴스. 그 전에는 base.
    # 여기선 단순히 effects 가 lane 에 전달됐는지 확인.
    assert len(lane.effects()) == 1
