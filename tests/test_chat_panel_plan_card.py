"""_PlanCard — ✓/✗ 시그널 + ✗ 후 textarea 등장 + [전송]/[그냥 닫기]."""
from __future__ import annotations

import pytest

from screen_recorder.ui.agent.chat_panel import _PlanCard


@pytest.fixture
def card(qtbot):
    c = _PlanCard(plan_id="plan_abc", summary="필러 cut", markdown="1. cut\n2. cut")
    qtbot.addWidget(c)
    # 보이게 — 일부 isVisible 체크는 show() 가 필요할 수 있음.
    c.show()
    return c


def test_pending_state_shows_approve_reject_buttons(card) -> None:
    assert card._approve_btn.isVisible()
    assert card._reject_btn.isVisible()
    assert not card._reason_input.isVisible()
    assert not card._send_reason_btn.isVisible()


def test_approve_emits_approved_signal(card, qtbot) -> None:
    with qtbot.waitSignal(card.approved, timeout=500):
        card._approve_btn.click()
    # 클릭 후 버튼 비활성화.
    assert not card._approve_btn.isEnabled()
    assert not card._reject_btn.isEnabled()


def test_reject_shows_textarea_and_two_buttons(card, qtbot) -> None:
    card._reject_btn.click()
    assert card._reason_input.isVisible()
    assert card._send_reason_btn.isVisible()
    assert card._close_no_reason_btn.isVisible()
    # 원래 ✓/✗ 는 비활성.
    assert not card._approve_btn.isEnabled()
    assert not card._reject_btn.isEnabled()


def test_send_reason_emits_rejected_with_text(card, qtbot) -> None:
    card._reject_btn.click()
    card._reason_input.setPlainText("필러는 빼지마")
    with qtbot.waitSignal(card.rejected, timeout=500) as sig:
        card._send_reason_btn.click()
    assert sig.args == ["필러는 빼지마"]


def test_close_no_reason_emits_rejected_with_empty_string(card, qtbot) -> None:
    card._reject_btn.click()
    with qtbot.waitSignal(card.rejected, timeout=500) as sig:
        card._close_no_reason_btn.click()
    assert sig.args == [""]


def test_plan_id_accessor(card) -> None:
    assert card.plan_id() == "plan_abc"


def test_mark_externally_resolved_approved(card) -> None:
    """외부에서 (예: PlanGate.cancel_all) 결정된 경우 — 버튼 비활성 + 표시 변경."""
    card.mark_externally_resolved("approved")
    assert not card._approve_btn.isEnabled()
    assert not card._reject_btn.isEnabled()


def test_mark_externally_resolved_cancelled(card) -> None:
    card.mark_externally_resolved("cancelled")
    assert not card._approve_btn.isEnabled()
    assert not card._reject_btn.isEnabled()
