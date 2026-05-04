"""PlayerControls 의 트림 추가 동작."""
from __future__ import annotations

import pytest

from screen_recorder.ui.video.player_controls import PlayerControls


@pytest.fixture
def controls(qtbot):
    c = PlayerControls()
    qtbot.addWidget(c)
    c.set_duration_ms(10_000)
    return c


def test_trim_button_disabled_initially(controls):
    assert controls.cut_btn.isEnabled() is False


def test_trim_button_disabled_with_only_in(controls):
    controls.set_in_ms(2_000)
    assert controls.cut_btn.isEnabled() is False


def test_trim_button_enabled_with_both(controls):
    controls.set_in_ms(2_000)
    controls.set_out_ms(5_000)
    assert controls.cut_btn.isEnabled() is True


def test_trim_lane_hidden_until_marked(controls):
    """평소엔 트림 레인 숨김."""
    assert controls.trim_row.isVisible() is False or controls.trim_row.isHidden() is True


def test_trim_lane_visible_after_in_set(controls, qtbot):
    controls.show()
    qtbot.waitExposed(controls)
    controls.set_in_ms(2_000)
    assert controls.trim_row.isVisibleTo(controls)


def test_clear_resets_state_and_button(controls):
    controls.set_in_ms(2_000)
    controls.set_out_ms(5_000)
    controls.clear_trim()
    assert controls.in_ms() is None
    assert controls.out_ms() is None
    assert controls.cut_btn.isEnabled() is False


def test_swap_when_out_before_in(controls):
    """out 이 in 보다 앞이면 자동 swap (PlayerControls 책임)."""
    controls.set_in_ms(5_000)
    controls.set_out_ms(2_000)
    assert controls.in_ms() == 2_000
    assert controls.out_ms() == 5_000


def test_too_short_blocks_button(controls):
    """0.1초 미만 구간은 ✂ 버튼 비활성화."""
    controls.set_in_ms(2_000)
    controls.set_out_ms(2_050)
    assert controls.cut_btn.isEnabled() is False


def test_trim_execute_emits_signal(controls, qtbot):
    controls.set_in_ms(1_000)
    controls.set_out_ms(4_000)
    with qtbot.waitSignal(controls.trim_execute_requested, timeout=500) as blocker:
        controls.cut_btn.click()
    assert blocker.args == [1_000, 4_000]


def test_trim_lane_in_changed_updates_state(controls):
    """TrimLane 핸들 드래그 → in_changed → PlayerControls.set_in_ms 가 갱신."""
    controls.set_in_ms(2_000)
    controls.set_out_ms(8_000)
    controls.trim_lane.in_changed.emit(3_000)
    assert controls.in_ms() == 3_000


def test_cut_enter_btn_marks_in_at_current_position(controls, qtbot):
    """컨트롤바의 ✂ 진입 버튼 — 현재 위치를 in 점으로 마크 ([ 키와 동일)."""
    controls.set_position_ms(3_500)
    assert controls.in_ms() is None      # 사전 조건
    controls.cut_enter_btn.click()
    assert controls.in_ms() == 3_500
    # 트림 row 도 같이 등장
    controls.show()
    qtbot.waitExposed(controls)
    assert controls.trim_row.isVisibleTo(controls)


def test_cut_enter_btn_always_visible(controls, qtbot):
    """진입 버튼은 in/out 마크 여부와 무관하게 항상 표시."""
    controls.show()
    qtbot.waitExposed(controls)
    assert controls.cut_enter_btn.isVisibleTo(controls)
    # in 점 마크 후에도 그대로
    controls.set_in_ms(1_000)
    assert controls.cut_enter_btn.isVisibleTo(controls)


def test_seek_slider_hidden_when_trim_active(controls, qtbot):
    """트림 row 활성 시 시크 슬라이더 숨김 — 트림 레인이 시크 역할 겸함."""
    controls.show()
    qtbot.waitExposed(controls)
    assert controls.seek_slider.isVisibleTo(controls)
    controls.set_in_ms(2_000)
    assert not controls.seek_slider.isVisibleTo(controls)
    # clear 시 다시 보임
    controls.clear_trim()
    assert controls.seek_slider.isVisibleTo(controls)


def test_mark_in_btn_uses_current_position(controls):
    controls.set_position_ms(4_500)
    controls.set_in_ms(1_000)   # 트림 모드 진입
    controls.mark_in_btn.click()
    assert controls.in_ms() == 4_500


def test_mark_out_btn_uses_current_position(controls):
    controls.set_position_ms(7_200)
    controls.set_in_ms(1_000)
    controls.mark_out_btn.click()
    assert controls.out_ms() == 7_200
