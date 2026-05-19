"""End-to-end smoke — plan submit → UI ✓ → propose 통과 흐름.

실제 Claude SDK 호출은 mock — PlanGate + ChatPanel + mutation tools 의 wiring 만 검증.
"""
from __future__ import annotations

import asyncio

from screen_recorder.agent.adapter import VideoSessionAdapter
from screen_recorder.agent.plan_gate import PlanGate
from screen_recorder.agent.proposals import ProposalQueue
from screen_recorder.agent.tools.mutation import make_mutation_tools
from screen_recorder.ui.agent.chat_panel import ChatPanel, _PlanCard


class _Stub(VideoSessionAdapter):
    def has_active_video(self): return True
    def active_video_path(self): return "/x.mp4"
    def active_sidecar(self): return {"effects": []}
    def active_duration_ms(self): return 60_000
    def active_position_ms(self): return 0
    def active_source_duration_ms(self): return 60_000


def test_end_to_end_approve_path(qtbot) -> None:
    """submit_plan → UI ✓ → propose_effect → 큐 적재."""
    gate = PlanGate()
    queue = ProposalQueue()
    adapter = _Stub()
    tools = {t.name: t for t in make_mutation_tools(adapter, queue, None, gate)}

    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    async def claude_flow():
        # 1. submit_plan — PlanCard 가 UI 에 뜸.
        submit_task = asyncio.create_task(tools["submit_plan"].handler({
            "summary": "필러 cut", "markdown": "1. cut",
        }))
        # UI 에서 ✓ 클릭 시뮬레이션 — submit 직후.
        await asyncio.sleep(0.05)
        last_idx = panel._messages_lay.count() - 1
        card = panel._messages_lay.itemAt(last_idx).widget()
        assert isinstance(card, _PlanCard)
        card._approve_btn.click()
        # submit_plan 응답 받기.
        sp_result = await submit_task
        assert "true" in sp_result["content"][0]["text"].lower()

        # 2. propose_effect — 이제 통과해야.
        pe_result = await tools["propose_effect"].handler({
            "type": "caption",
            "payload": {"in_ms": 0, "out_ms": 1000, "text": "hi"},
        })
        assert "queued" in pe_result["content"][0]["text"].lower()

    asyncio.run(claude_flow())
    assert queue.count() == 1


def test_end_to_end_reject_path(qtbot) -> None:
    """submit_plan → UI ✗ + reason → 응답에 reason 포함 → propose_effect 여전히 차단."""
    gate = PlanGate()
    queue = ProposalQueue()
    adapter = _Stub()
    tools = {t.name: t for t in make_mutation_tools(adapter, queue, None, gate)}

    panel = ChatPanel(initial_model_id="claude-sonnet-4-6", initial_show_thinking=False,
                       plan_gate=gate)
    qtbot.addWidget(panel)

    async def claude_flow():
        submit_task = asyncio.create_task(tools["submit_plan"].handler({
            "summary": "s", "markdown": "m",
        }))
        await asyncio.sleep(0.05)
        last_idx = panel._messages_lay.count() - 1
        card = panel._messages_lay.itemAt(last_idx).widget()
        # ✗ 클릭 → textarea 등장.
        card._reject_btn.click()
        card._reason_input.setPlainText("필러는 빼지마")
        card._send_reason_btn.click()
        sp_result = await submit_task
        text = sp_result["content"][0]["text"]
        assert "false" in text.lower()
        assert "필러는 빼지마" in text

        # propose_effect 는 여전히 차단.
        pe_result = await tools["propose_effect"].handler({
            "type": "caption",
            "payload": {"in_ms": 0, "out_ms": 1000, "text": "hi"},
        })
        assert "submit_plan" in pe_result["content"][0]["text"]

    asyncio.run(claude_flow())
    assert queue.count() == 0


def test_new_user_message_invalidates_previous_approval(qtbot) -> None:
    """사용자가 첫 plan 승인 → 두 번째 메시지 보냄 → 두 번째에선 새 plan 필요."""
    gate = PlanGate()
    queue = ProposalQueue()
    adapter = _Stub()
    tools = {t.name: t for t in make_mutation_tools(adapter, queue, None, gate)}

    # 첫 메시지 사이클.
    async def first_cycle():
        pid1 = gate.submit("s1", "m1")
        gate.approve(pid1)
        await tools["propose_effect"].handler({
            "type": "caption", "payload": {"in_ms": 0, "out_ms": 1000, "text": "a"},
        })
    asyncio.run(first_cycle())
    assert queue.count() == 1

    # 사용자 새 메시지 — AgentRuntime._on_user_message_outgoing 와 동등.
    gate.cancel_all()
    gate.invalidate_approval()

    # 두 번째 메시지에서 plan 없이 propose → 차단.
    async def second_attempt():
        return await tools["propose_effect"].handler({
            "type": "caption", "payload": {"in_ms": 1000, "out_ms": 2000, "text": "b"},
        })
    result = asyncio.run(second_attempt())
    assert "submit_plan" in result["content"][0]["text"]
    assert queue.count() == 1   # 두 번째는 차단됐으므로.
