"""VideoTab — 배속 구간 진입/이탈 시 player.set_playback_rate 자동 전환."""
from __future__ import annotations

from pathlib import Path

import pytest

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.effects.types.speed import SpeedEffect
from screen_recorder.ui.video_tab import VideoTab


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 200_000)
    return p


def _make_tab(qtbot, sample_mp4, tmp_path):
    tab = VideoTab(
        path=sample_mp4, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)
    tab.set_edit_mode(True)
    return tab


def _stub_player(tab):
    """player 의 set_playback_rate / set_muted / is_muted 를 list 로 캡처."""
    rate_calls: list[float] = []
    mute_calls: list[bool] = []
    tab.player.set_playback_rate = lambda r: rate_calls.append(float(r))
    tab.player.set_muted = lambda m: mute_calls.append(bool(m))
    tab.player.is_muted = lambda: False
    return rate_calls, mute_calls


def test_position_inside_speed_region_sets_rate(qtbot, sample_mp4, tmp_path):
    """위치가 SpeedEffect 구간 안에 들어오면 player.set_playback_rate(rate) 호출."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, _ = _stub_player(tab)

    # 2-7초 구간에 2.0× 배속 추가
    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=2000, out_ms=7000, rate=2.0)
    )

    # 위치가 구간 안 (3000ms) → rate 2.0 적용
    tab._on_position_for_speed(3000)
    assert rate_calls == [2.0]
    assert tab._active_speed_id is not None


def test_position_outside_speed_region_resets_rate(qtbot, sample_mp4, tmp_path):
    """구간 진입 → 이탈 시 rate 1.0 으로 복원."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, _ = _stub_player(tab)

    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=2000, out_ms=7000, rate=2.0)
    )

    # 진입
    tab._on_position_for_speed(3000)
    # 이탈 (7500ms — out_ms 7000 보다 뒤)
    tab._on_position_for_speed(7500)
    assert rate_calls[-1] == 1.0
    assert tab._active_speed_id is None


def test_no_speed_no_rate_call(qtbot, sample_mp4, tmp_path):
    """SpeedEffect 가 없는 사이드카 — 위치 변화는 rate 호출을 만들지 않음."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, _ = _stub_player(tab)

    # 효과 0 개 상태에서 여러 위치 호출
    tab._on_position_for_speed(0)
    tab._on_position_for_speed(3000)
    tab._on_position_for_speed(8000)

    assert rate_calls == []
    assert tab._active_speed_id is None


def test_active_id_does_not_re_apply_rate(qtbot, sample_mp4, tmp_path):
    """동일 구간 안에서 위치가 여러 번 갱신돼도 rate 호출은 진입 1회만."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, _ = _stub_player(tab)

    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=2000, out_ms=7000, rate=2.0)
    )

    tab._on_position_for_speed(3000)
    tab._on_position_for_speed(4000)
    tab._on_position_for_speed(5000)
    assert rate_calls == [2.0]   # 진입 1회만


def test_mute_audio_mode_mutes_during_region(qtbot, sample_mp4, tmp_path):
    """audio='mute' SpeedEffect — 구간 진입 시 set_muted(True), 이탈 시 복원."""
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, mute_calls = _stub_player(tab)

    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=2000, out_ms=7000, rate=2.0, audio="mute")
    )

    tab._on_position_for_speed(3000)   # 진입
    assert True in mute_calls          # 음소거 ON
    tab._on_position_for_speed(8000)   # 이탈
    assert mute_calls[-1] is False     # 음소거 복원 (is_muted=False 였음)


def test_mute_to_auto_adjacent_regions_restore_mute(qtbot, sample_mp4, tmp_path):
    """인접한 mute → auto SpeedEffect 전환 시 두 번째 구간에서 mute 복원.

    이전 버그: mute 구간에서 인접한 auto 구간으로 바로 진입 시, 첫 구간에서 활성
    인지된 _speed_prev_muted 가 두 번째 구간에서도 풀리지 않아 음소거가 남음.
    """
    tab = _make_tab(qtbot, sample_mp4, tmp_path)
    rate_calls, mute_calls = _stub_player(tab)

    # 1초~3초 mute, 3초~5초 auto (인접)
    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=1000, out_ms=3000, rate=2.0, audio="mute")
    )
    tab._edit_controller.add_effect(
        SpeedEffect(in_ms=3000, out_ms=5000, rate=2.0, audio="auto")
    )

    tab._on_position_for_speed(2000)   # mute 구간 진입
    assert True in mute_calls
    tab._on_position_for_speed(4000)   # auto 구간 진입 — mute 복원되어야 함
    # 마지막 mute 호출이 False (is_muted 가 False 였으므로 그 값으로 복원)
    assert mute_calls[-1] is False
