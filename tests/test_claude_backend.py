"""ClaudeBackend 단위 테스트 — claude_agent_sdk mock.

런타임 통합 (Qt Signal) 은 test_agent_runtime_after_refactor.py 에서. 여기는 백엔드
내부 로직 (SDK 호출, AgentMessage/AgentEvent 변환) 만.
"""
from __future__ import annotations

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
