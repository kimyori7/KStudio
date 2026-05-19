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


# ============================================================
# ChatPanel ↔ PlanGate 통합 — plan_submitted 시그널 → PlanCard 삽입 → ✓/✗ → gate 호출
# ============================================================
def test_chat_panel_creates_plan_card_on_plan_submitted(qtbot) -> None:
    """plan_gate.plan_submitted emit → ChatPanel 의 message 영역에 _PlanCard 1개 추가."""
    import asyncio as _asyncio
    from screen_recorder.agent.plan_gate import PlanGate
    from screen_recorder.ui.agent.chat_panel import ChatPanel, _PlanCard

    gate = PlanGate()
    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    before = panel.message_count()

    async def submit():
        return gate.submit("필러 cut", "1. cut\n2. cut")
    _asyncio.run(submit())

    # plan_submitted 는 DirectConnection (same thread) — emit 직후 슬롯 도착.
    assert panel.message_count() == before + 1
    last_idx = panel._messages_lay.count() - 1
    bubble = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(bubble, _PlanCard)
    assert bubble.plan_id().startswith("plan_")


def test_plan_card_approve_calls_gate_approve(qtbot) -> None:
    import asyncio as _asyncio
    from screen_recorder.agent.plan_gate import PlanGate
    from screen_recorder.ui.agent.chat_panel import ChatPanel, _PlanCard

    gate = PlanGate()
    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    async def submit():
        return gate.submit("s", "m")
    _asyncio.run(submit())

    last_idx = panel._messages_lay.count() - 1
    card = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(card, _PlanCard)

    # 사전 require_approval 은 실패해야 (승인 전).
    with pytest.raises(ValueError):
        gate.require_approval()

    card._approve_btn.click()

    # 게이트가 승인 상태가 됐어야.
    gate.require_approval()   # 예외 없으면 OK.


def test_plan_card_reject_with_reason_calls_gate_reject(qtbot) -> None:
    import asyncio as _asyncio
    from screen_recorder.agent.plan_gate import PlanGate
    from screen_recorder.ui.agent.chat_panel import ChatPanel, _PlanCard

    gate = PlanGate()
    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    async def submit():
        return gate.submit("s", "m")
    _asyncio.run(submit())

    last_idx = panel._messages_lay.count() - 1
    card = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(card, _PlanCard)

    # Reject 흐름.
    card._reject_btn.click()
    card._reason_input.setPlainText("필러는 빼지마")
    card._send_reason_btn.click()

    # 게이트는 승인 안 됐어야.
    with pytest.raises(ValueError):
        gate.require_approval()


def test_cancel_all_locks_stale_plan_card(qtbot) -> None:
    """새 사용자 메시지 / Claude cancel 시 PlanGate.cancel_all 호출 → 화면의 stale
    PlanCard 가 자동으로 '취소됨' 으로 잠겨 사용자가 무의미한 ✓ 클릭하지 않게 보호.
    """
    import asyncio as _asyncio
    from screen_recorder.agent.plan_gate import PlanGate
    from screen_recorder.ui.agent.chat_panel import ChatPanel, _PlanCard

    gate = PlanGate()
    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    async def submit():
        return gate.submit("s", "m")
    pid = _asyncio.run(submit())

    last_idx = panel._messages_lay.count() - 1
    card = panel._messages_lay.itemAt(last_idx).widget()
    assert isinstance(card, _PlanCard)
    # 아직 pending — ✓/✗ 활성.
    assert card._approve_btn.isEnabled()
    assert card._reject_btn.isEnabled()

    # 외부 cancel — AgentRuntime._on_user_message_outgoing 동등.
    gate.cancel_all()

    # 카드의 ✓/✗ 가 비활성화돼야.
    assert not card._approve_btn.isEnabled()
    assert not card._reject_btn.isEnabled()
    # registry 에서 제거됐어야.
    assert pid not in panel._plan_cards
