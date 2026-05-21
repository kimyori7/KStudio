"""runtime.py 리팩토링 후 외부 동작 100% 동일 검증.

ClaudeBackend 가 내부에서 호출되지만, ChatPanel 시점에서는 Signal 발화 패턴이
완전히 같아야 함.

NOTE: 계획서(plan)에서는 Agent 별칭을 사용했지만 실제 클래스명은 AgentRuntime.
이 파일은 AgentRuntime 을 직접 사용 — chat_panel.py API 0줄 변경 보장.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from screen_recorder.agent.runtime import AgentRuntime, AgentMessage, AgentEvent
from screen_recorder.agent.backends import ChatInput


@pytest.fixture
def mock_video_tools():
    """VideoTools mock — mcp_server() + tool_names() + plan_gate() 만 필요."""
    vt = MagicMock()
    vt.mcp_server.return_value = MagicMock()
    vt.tool_names.return_value = ["get_video_state"]
    vt.plan_gate.return_value = MagicMock()
    return vt


@pytest.fixture
def agent(mock_video_tools, tmp_path, qtbot):
    """AgentRuntime 인스턴스 — 테스트 종료 시 정리."""
    a = AgentRuntime(video_tools=mock_video_tools, cwd=tmp_path)
    yield a
    # 스레드가 시작됐으면 정리 (loop 를 stop 해서 deadlock 방지).
    if a._started:
        loop = a._thread._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        a._thread.quit()
        a._thread.wait(2000)


def test_agent_holds_claude_backend(agent):
    """AgentRuntime 이 내부적으로 ClaudeBackend 인스턴스를 갖는다."""
    from screen_recorder.agent.backends.claude_backend import ClaudeBackend
    assert isinstance(agent._backend, ClaudeBackend)


def test_set_model_updates_internal_field(agent):
    """set_model 호출이 _model 갱신."""
    agent.set_model("claude-opus-4-5")
    assert agent._model == "claude-opus-4-5"


def test_set_model_no_change_when_same_model(agent):
    """같은 모델 재설정은 no-op — _session_started 영향 없음."""
    agent._model = "claude-sonnet-4-6"
    agent._session_started = True
    agent.set_model("claude-sonnet-4-6")
    # 같은 모델이면 _session_started 리셋 안 됨.
    assert agent._session_started is True


def test_send_with_no_images_calls_backend_send_message(mock_video_tools, tmp_path, qtbot):
    """send() → backend.send_message(ChatInput(text=..., images=None))."""
    agent = AgentRuntime(video_tools=mock_video_tools, cwd=tmp_path)

    captured: list = []

    async def _fake_send(msg, emit_fn):
        captured.append(msg)
        emit_fn(AgentEvent(kind="started"))
        emit_fn(AgentMessage(role="assistant", text="응답"))
        emit_fn(AgentEvent(kind="done", detail="in=10 out=5"))

    agent._backend.send_message = _fake_send
    agent._backend.start_session = AsyncMock()

    events: list = []
    msgs: list = []
    agent.event_received.connect(events.append)
    agent.message_received.connect(msgs.append)

    try:
        agent.send("안녕하세요")
        qtbot.wait(400)   # worker 스레드가 emit 완료 대기

        assert len(captured) == 1
        assert isinstance(captured[0], ChatInput)
        assert captured[0].text == "안녕하세요"
        assert captured[0].images is None
        # Signal 통한 emit 도 정상 동작.
        assert any(isinstance(e, AgentEvent) and e.kind == "done" for e in events)
        assert any(isinstance(m, AgentMessage) and m.role == "assistant" for m in msgs)
    finally:
        if agent._started:
            loop = agent._thread._loop
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
            agent._thread.quit()
            agent._thread.wait(2000)


def test_send_with_images_passes_to_backend(mock_video_tools, tmp_path, qtbot):
    """send(images=[...]) → backend 가 ChatInput.images 로 받는다."""
    agent = AgentRuntime(video_tools=mock_video_tools, cwd=tmp_path)

    captured: list = []

    async def _fake_send(msg, emit_fn):
        captured.append(msg)
        emit_fn(AgentEvent(kind="done", detail=""))

    agent._backend.send_message = _fake_send
    agent._backend.start_session = AsyncMock()

    try:
        png = b"fake_png"
        agent.send("사진 봐", images=[png])
        qtbot.wait(400)

        assert len(captured) == 1
        assert captured[0].images == [png]
    finally:
        if agent._started:
            loop = agent._thread._loop
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
            agent._thread.quit()
            agent._thread.wait(2000)


def test_cancel_calls_backend_cancel(mock_video_tools, tmp_path, qtbot):
    """cancel() → backend.cancel() 가 호출된다."""
    agent = AgentRuntime(video_tools=mock_video_tools, cwd=tmp_path)
    agent._backend.cancel = AsyncMock()
    agent._backend.start_session = AsyncMock()

    async def _fake_send(msg, emit_fn):
        await asyncio.sleep(2.0)   # 무한 대기 — cancel 대상

    agent._backend.send_message = _fake_send

    try:
        agent.send("hi")
        qtbot.wait(120)
        agent.cancel()
        qtbot.wait(400)
        agent._backend.cancel.assert_called()
    finally:
        if agent._started:
            loop = agent._thread._loop
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
            agent._thread.quit()
            agent._thread.wait(2000)


def test_clear_session_resets_session_started(agent):
    """clear_session() → _session_started=False."""
    agent._session_started = True
    agent.clear_session()
    assert agent._session_started is False


def test_agent_default_model_is_sonnet(agent):
    """기본 모델이 claude-sonnet-4-6 (Pro 정액제 친화)."""
    assert "sonnet" in agent._model.lower()


def test_compact_session_no_op_before_start(agent):
    """스레드 미시작 시 compact_session 은 예외 없이 no-op."""
    agent.compact_session()   # 예외 없어야 함
    assert not agent._started
