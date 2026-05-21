"""ClaudeBackend 단위 테스트 — claude_agent_sdk mock.

런타임 통합 (Qt Signal) 은 test_agent_runtime_after_refactor.py 에서. 여기는 백엔드
내부 로직 (SDK 호출, AgentMessage/AgentEvent 변환) 만.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from screen_recorder.agent.backends.claude_backend import ClaudeBackend


@pytest.mark.asyncio
async def test_start_session_creates_client_on_first_send():
    """start_session 호출만으로는 client 생성 안 함 — 첫 send_message 에서 연결."""
    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    assert be._client is None
    assert be._model == "sonnet"
    assert be._system_prompt == "sys"
    # tools 는 dict 로 보관 — list 였던 초기 plan 형식 회귀 방지.
    assert isinstance(be._tools, dict)


@pytest.mark.asyncio
async def test_start_session_stores_tools_dict_contents():
    """tools dict 의 mcp_server + allowed_tools 가 그대로 보관됨."""
    be = ClaudeBackend(cwd="/tmp")
    sentinel_mcp = object()
    await be.start_session(
        system_prompt="sys",
        tools={"mcp_server": sentinel_mcp, "allowed_tools": ["a", "b"]},
        model="sonnet",
    )
    assert be._tools["mcp_server"] is sentinel_mcp
    assert be._tools["allowed_tools"] == ["a", "b"]


@pytest.mark.asyncio
async def test_close_disconnects_client():
    be = ClaudeBackend(cwd="/tmp")
    mock_client = MagicMock()
    mock_client.disconnect = AsyncMock()
    be._client = mock_client
    await be.close()
    mock_client.disconnect.assert_awaited_once()
    assert be._client is None


@pytest.mark.asyncio
async def test_close_noop_when_no_client():
    be = ClaudeBackend(cwd="/tmp")
    await be.close()   # 예외 없어야 함
    assert be._client is None


def test_supports_modality():
    be = ClaudeBackend(cwd="/tmp")
    assert be.supports_modality("image") is True
    assert be.supports_modality("audio") is False
    assert be.supports_modality("video") is False
    # text 는 modality 플래그가 아니라 항상 implicit — 호출자는 gate 하지 말 것.
    # 현 구현은 모든 비-image 를 False 반환하므로 text 도 False — 의도.
    assert be.supports_modality("text") is False


@pytest.mark.asyncio
async def test_cancel_cancels_current_task():
    """진행 중 task 가 있으면 cancel() 이 그 task 를 취소."""
    be = ClaudeBackend(cwd="/tmp")

    async def _long_running():
        await asyncio.sleep(10)

    task = asyncio.create_task(_long_running())
    be._current_task = task

    # task 가 즉시 동작 시작하도록 잠깐 yield.
    await asyncio.sleep(0)
    await be.cancel()

    # cancel 전파 대기.
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert task.cancelled()


@pytest.mark.asyncio
async def test_cancel_noop_when_no_task():
    """진행 중 task 가 없으면 cancel() 은 예외 없이 끝남."""
    be = ClaudeBackend(cwd="/tmp")
    assert be._current_task is None
    await be.cancel()   # 예외 없어야 함


@pytest.mark.asyncio
async def test_cancel_noop_when_task_already_done():
    """이미 완료된 task 가 들어 있으면 cancel() 호출해도 InvalidStateError 안 남."""
    be = ClaudeBackend(cwd="/tmp")

    async def _quick():
        return 42

    task = asyncio.create_task(_quick())
    await task   # 완료될 때까지 대기
    be._current_task = task
    assert task.done()
    await be.cancel()   # 예외 없어야 함
