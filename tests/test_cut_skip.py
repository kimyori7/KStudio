"""find_cut_skip_target — 재생 시 cut 자동 skip 결정 헬퍼.

2026-05-19 사용자 보고: "잘랐으면 잘린 부분이 보여야하는데 안보임" → 실제로는
'잘린 부분이 *재생되지 않아야* 한다' 는 의도. cut 효과는 사이드카 마커만이라
preview 재생에서 해당 구간 콘텐츠가 그대로 보임. 사용자가 export 결과를 미리
체감할 수 있도록 재생 중 cut 구간 진입 시 out_ms 로 점프.

다 (Inspector 체크박스) 가 추가되면 preview_skip=False 로 끄기 가능 (이 경우 원본
콘텐츠가 그대로 재생).
"""
from __future__ import annotations

from screen_recorder.effects.types.cut import CutEffect, find_cut_skip_target


def test_position_inside_cut_returns_out_ms() -> None:
    """cut [1000, 2000] 내부 — 1500ms 위치면 2000ms 로 skip 점프."""
    effects = [CutEffect(in_ms=1000, out_ms=2000)]
    assert find_cut_skip_target(effects, 1500) == 2000


def test_position_at_cut_in_ms_returns_out_ms() -> None:
    """경계 — in_ms 정확히 도달하면 skip (포함)."""
    effects = [CutEffect(in_ms=1000, out_ms=2000)]
    assert find_cut_skip_target(effects, 1000) == 2000


def test_position_at_cut_out_ms_returns_none() -> None:
    """경계 — out_ms 는 cut 밖 (배타적). 이미 빠져나간 상태."""
    effects = [CutEffect(in_ms=1000, out_ms=2000)]
    assert find_cut_skip_target(effects, 2000) is None


def test_position_outside_cut_returns_none() -> None:
    effects = [CutEffect(in_ms=1000, out_ms=2000)]
    assert find_cut_skip_target(effects, 500) is None
    assert find_cut_skip_target(effects, 3000) is None


def test_splice_cut_never_triggers_skip() -> None:
    """in_ms == out_ms 는 splice point — 0폭이라 skip 의미 없음."""
    effects = [CutEffect(in_ms=1500, out_ms=1500)]
    assert find_cut_skip_target(effects, 1500) is None


def test_preview_skip_false_disables_skip() -> None:
    """다(Inspector) 체크박스 OFF 시 — preview_skip=False 면 skip 안 함."""
    effects = [CutEffect(in_ms=1000, out_ms=2000, preview_skip=False)]
    assert find_cut_skip_target(effects, 1500) is None


def test_multiple_cuts_inside_first() -> None:
    """여러 cut 중 첫 매치 반환."""
    effects = [
        CutEffect(in_ms=1000, out_ms=2000),
        CutEffect(in_ms=5000, out_ms=6000),
    ]
    assert find_cut_skip_target(effects, 1500) == 2000
    assert find_cut_skip_target(effects, 5500) == 6000


def test_non_cut_effects_ignored() -> None:
    """caption / zoom 등 비 cut 효과는 skip 대상 아님."""
    from screen_recorder.effects.types.caption import CaptionEffect
    effects = [
        CaptionEffect(in_ms=1000, out_ms=2000, text="hi"),
        CutEffect(in_ms=3000, out_ms=4000),
    ]
    # 캡션 구간 안 — skip 없음.
    assert find_cut_skip_target(effects, 1500) is None
    # cut 구간 안 — skip.
    assert find_cut_skip_target(effects, 3500) == 4000


def test_empty_effects_returns_none() -> None:
    assert find_cut_skip_target([], 5000) is None


def test_cut_default_preview_skip_is_true() -> None:
    """기본값 — Claude 가 cut 추가하면 즉시 skip 동작 (사용자 명시 안 해도)."""
    c = CutEffect(in_ms=1000, out_ms=2000)
    assert c.preview_skip is True


def test_video_tab_on_position_calls_seek_when_inside_cut(qtbot, tmp_path) -> None:
    """VideoTab._on_position_for_cut_skip — 통합 점검: cut 안 ms 들어오면
    _segment_ctrl.seek_combined_ms(cut.out_ms) 정확히 1회.

    wiring 없으면 가/나/다 사용자 가치 0 — 단위 테스트가 다 통과해도 시그널 연결이
    안 됐으면 실제로 안 돕음. VideoTab 풀 생성은 무겁고 fake mp4 못 읽지만 (사전부터
    moov atom 없음 워닝), 메서드 직접 호출 + sidecar 주입으로 검증 가능.
    """
    from unittest.mock import MagicMock
    from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
    from screen_recorder.effects.sidecar import Sidecar, Trim
    from screen_recorder.ui.video_tab import VideoTab

    fake_video = tmp_path / "a.mp4"
    fake_video.write_bytes(b"\x00" * 4096)
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    tab = VideoTab(
        path=fake_video, source_label="a.mp4", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=sidecar_dir,
    )
    qtbot.addWidget(tab)
    # sidecar 에 cut 효과 1개 주입 (paint/edit_mode 없이 raw 주입).
    sc = Sidecar(
        source_path=str(fake_video), source_hash="h",
        trim=Trim(in_ms=0, out_ms=10_000),
        effects=[CutEffect(in_ms=2000, out_ms=3000)],
    )
    tab._edit_controller._sidecar = sc

    # _segment_ctrl 의 seek_combined_ms 만 spy — 실제 player 흔들지 않음.
    tab._segment_ctrl.seek_combined_ms = MagicMock()

    # cut 안 (2500ms) 도달 시뮬레이션.
    tab._on_position_for_cut_skip(2500)
    tab._segment_ctrl.seek_combined_ms.assert_called_once_with(3000)

    # cut 밖 (5000ms) 도달 — seek 추가 호출 안 됨.
    tab._segment_ctrl.seek_combined_ms.reset_mock()
    tab._on_position_for_cut_skip(5000)
    tab._segment_ctrl.seek_combined_ms.assert_not_called()


def test_chained_cuts_each_skips_into_next() -> None:
    """연속 cut [2000,3000]+[3000,4000] — 첫 skip 후 도착점이 두 번째 cut 의 in_ms 와
    일치하면 다음 tick 에 또 skip 발화. 정상 — 두 cut 을 한 번에 점프하는 효과.
    """
    effects = [
        CutEffect(in_ms=2000, out_ms=3000),
        CutEffect(in_ms=3000, out_ms=4000),
    ]
    # 첫 cut 안 — 3000 으로 skip.
    assert find_cut_skip_target(effects, 2500) == 3000
    # 3000 도달 — 두 번째 cut.in_ms 와 동일 → 다시 skip 4000 으로.
    assert find_cut_skip_target(effects, 3000) == 4000
    # 4000 도달 — cut 밖, skip 종료.
    assert find_cut_skip_target(effects, 4000) is None
