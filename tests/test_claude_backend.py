"""ClaudeBackend 단위 테스트 — claude_agent_sdk mock.

런타임 통합 (Qt Signal) 은 test_agent_runtime_after_refactor.py 에서. 여기는 백엔드
내부 로직 (SDK 호출, AgentMessage/AgentEvent 변환) 만.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def sdk_mock(monkeypatch):
    """claude_agent_sdk 를 mock 으로 교체.

    반환: (mock_sdk_module, mock_client). 호출자는 mock_client.receive_response 를
    원하는 async generator 함수로 교체해 응답 시퀀스 정의.

    isinstance 검사 우회 — runtime 코드의 모든 SDK 타입 체크가 동작하도록 type
    객체들도 mock_sdk 에 attribute 로 세팅.
    """
    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.query = AsyncMock()
    # default: 빈 응답 — 호출자가 receive_response 를 교체해서 사용.
    async def _empty_receive():
        if False:
            yield None   # generator 형태 보장.
    mock_client.receive_response = lambda: _empty_receive()

    mock_sdk = MagicMock()
    mock_sdk.ClaudeSDKClient = lambda options: mock_client
    mock_sdk.ClaudeAgentOptions = MagicMock(return_value=MagicMock())
    # isinstance() 검사용 — 각 테스트가 실제 데이터 클래스를 덮어쓰기도 함.
    mock_sdk.AssistantMessage = type("AssistantMessage", (), {"content": [], "usage": None})
    mock_sdk.ResultMessage = type("ResultMessage", (), {"usage": {}})
    mock_sdk.UserMessage = type("UserMessage", (), {})
    mock_sdk.StreamEvent = type("StreamEvent", (), {})
    mock_sdk.TextBlock = type("TextBlock", (), {})
    mock_sdk.ThinkingBlock = type("ThinkingBlock", (), {})
    mock_sdk.ToolUseBlock = type("ToolUseBlock", (), {})
    mock_sdk.ToolResultBlock = type("ToolResultBlock", (), {})

    monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", mock_sdk)
    yield mock_sdk, mock_client


@pytest.mark.asyncio
async def test_send_message_text_emits_text_block(sdk_mock):
    """텍스트 query → AssistantMessage TextBlock → emit AgentMessage(role='assistant')."""
    from screen_recorder.agent.runtime import AgentMessage, AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _FakeTextBlock:
        text = "안녕하세요"

    class _FakeAssistantMsg:
        content = [_FakeTextBlock()]
        usage = None

    class _FakeResultMsg:
        usage = {"input_tokens": 100, "output_tokens": 50}

    async def _fake_receive():
        yield _FakeAssistantMsg()
        yield _FakeResultMsg()

    mock_client.receive_response = lambda: _fake_receive()
    # isinstance 검사가 _FakeAssistantMsg / _FakeResultMsg 통과하도록.
    mock_sdk.AssistantMessage = _FakeAssistantMsg
    mock_sdk.ResultMessage = _FakeResultMsg
    mock_sdk.TextBlock = _FakeTextBlock

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="안녕"), received.append)

    assert any(isinstance(r, AgentEvent) and r.kind == "started" for r in received)
    text_msgs = [r for r in received
                  if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert len(text_msgs) == 1
    assert text_msgs[0].text == "안녕하세요"
    done_evs = [r for r in received if isinstance(r, AgentEvent) and r.kind == "done"]
    assert len(done_evs) == 1


@pytest.mark.asyncio
async def test_send_message_cancel_emits_error_and_closes_client(sdk_mock):
    """진행 중 send_message 에 CancelledError → 'error' 이벤트 emit + client close + re-raise."""
    from screen_recorder.agent.runtime import AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    # receive_response 가 무한 대기 — 외부에서 cancel 대상.
    async def _slow_receive():
        await asyncio.sleep(1.0)
        yield None  # 도달 안 함

    mock_client.receive_response = lambda: _slow_receive()

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")

    received: list = []
    async def _runner():
        await be.send_message(ChatInput(text="hi"), received.append)

    task = asyncio.create_task(_runner())
    # send_message 가 receive 루프 진입할 시간.
    await asyncio.sleep(0.05)
    await be.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # error 이벤트 + 한국어 메시지.
    error_evs = [r for r in received
                  if isinstance(r, AgentEvent) and r.kind == "error"]
    assert any("취소" in e.detail for e in error_evs)
    # close() 가 호출돼 _client = None.
    assert be._client is None
    mock_client.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_send_message_clears_current_task_on_success(sdk_mock):
    """정상 종료 후 _current_task = None — 다음 cancel 이 stale task 가리키지 않음."""
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _AM:
        content = []
        usage = None

    class _Result:
        usage = {}

    async def _r():
        yield _AM()
        yield _Result()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ResultMessage = _Result

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    await be.send_message(ChatInput(text="hi"), lambda _: None)

    assert be._current_task is None


@pytest.mark.asyncio
async def test_send_message_clears_current_task_on_cancel(sdk_mock):
    """cancel 경로 후에도 _current_task = None — finally 블록 보장."""
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    async def _slow():
        await asyncio.sleep(1.0)
        yield None

    mock_client.receive_response = lambda: _slow()

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")

    async def _runner():
        await be.send_message(ChatInput(text="hi"), lambda _: None)

    task = asyncio.create_task(_runner())
    await asyncio.sleep(0.05)
    await be.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert be._current_task is None


@pytest.mark.asyncio
async def test_send_message_stream_event_emits_partial_text(sdk_mock):
    """StreamEvent text_delta → AgentMessage 즉시 emit (token streaming)."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _FakeStreamEvent:
        def __init__(self, ev_dict):
            self.event = ev_dict

    async def _fake_receive():
        # message_start → delta 두 번 → 빈 AM → result.
        yield _FakeStreamEvent({"type": "message_start"})
        yield _FakeStreamEvent({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": "안녕"}})
        yield _FakeStreamEvent({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": "하세요"}})

        class _AM:
            content = []
            usage = None
        yield _AM()

        class _Result:
            usage = {}
        yield _Result()

    mock_client.receive_response = lambda: _fake_receive()
    mock_sdk.StreamEvent = _FakeStreamEvent

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    assistant_texts = [r.text for r in received
                        if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert assistant_texts == ["안녕", "하세요"]


@pytest.mark.asyncio
async def test_send_message_thinking_delta_emits_thinking(sdk_mock):
    """StreamEvent thinking_delta → role='thinking'."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _SE:
        def __init__(self, d): self.event = d

    async def _fake_receive():
        yield _SE({"type": "message_start"})
        yield _SE({"type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "흠..."}})
        class _AM: content = []; usage = None
        yield _AM()
        class _R: usage = {}
        yield _R()

    mock_client.receive_response = lambda: _fake_receive()
    mock_sdk.StreamEvent = _SE

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    thinking_texts = [r.text for r in received
                       if isinstance(r, AgentMessage) and r.role == "thinking"]
    assert thinking_texts == ["흠..."]


@pytest.mark.asyncio
async def test_stream_text_delta_skips_textblock_in_assistant_msg(sdk_mock):
    """partial 로 텍스트가 흐른 경우 AssistantMessage 의 TextBlock 은 skip (중복 방지)."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _SE:
        def __init__(self, d): self.event = d

    class _FakeTextBlock:
        text = "안녕하세요"   # AM 의 풀텍스트 — 중복 emit 되면 안 됨.

    class _FakeAssistantMsg:
        content = [_FakeTextBlock()]
        usage = None

    async def _r():
        yield _SE({"type": "message_start"})
        yield _SE({"type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "안녕하세요"}})
        yield _FakeAssistantMsg()
        class _R: usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.StreamEvent = _SE
    mock_sdk.TextBlock = _FakeTextBlock
    mock_sdk.AssistantMessage = _FakeAssistantMsg

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    # delta 1번 + AM 의 TextBlock skip → 총 1개만.
    assistant_msgs = [r for r in received
                       if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].text == "안녕하세요"


@pytest.mark.asyncio
async def test_send_message_thinking_block_in_assistant_msg(sdk_mock):
    """partial 안 흐른 경우 ThinkingBlock → role='thinking' emit."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _ThinkingBlk:
        thinking = "추론 중..."

    class _AM:
        content = [_ThinkingBlk()]
        usage = None

    async def _r():
        yield _AM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ThinkingBlock = _ThinkingBlk

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    thinking = [r for r in received if isinstance(r, AgentMessage) and r.role == "thinking"]
    assert len(thinking) == 1
    assert thinking[0].text == "추론 중..."


@pytest.mark.asyncio
async def test_thinking_delta_skips_thinkingblock_in_assistant_msg(sdk_mock):
    """partial 로 thinking_delta 가 흘렀으면 AM 의 ThinkingBlock 은 skip (중복 방지)."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _SE:
        def __init__(self, d): self.event = d

    class _ThinkingBlk:
        thinking = "추론 중..."

    class _AM:
        content = [_ThinkingBlk()]
        usage = None

    async def _r():
        yield _SE({"type": "message_start"})
        yield _SE({"type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "추론 중..."}})
        yield _AM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.StreamEvent = _SE
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ThinkingBlock = _ThinkingBlk

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    thinking = [r for r in received if isinstance(r, AgentMessage) and r.role == "thinking"]
    # delta 1번만 — AM 의 ThinkingBlock 은 skip.
    assert len(thinking) == 1
    assert thinking[0].text == "추론 중..."


@pytest.mark.asyncio
async def test_send_message_tool_use_block_emits_tool_use(sdk_mock):
    """ToolUseBlock → AgentEvent(kind='tool_use') + AgentMessage(role='tool_use')."""
    from screen_recorder.agent.runtime import AgentMessage, AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _TUB:
        name = "mcp__kstudio_video__get_video_state"
        input = {"foo": "bar"}

    class _AM:
        content = [_TUB()]
        usage = None

    async def _r():
        yield _AM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ToolUseBlock = _TUB

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    tool_use_evs = [r for r in received
                     if isinstance(r, AgentEvent) and r.kind == "tool_use"]
    assert len(tool_use_evs) == 1
    assert "get_video_state" in tool_use_evs[0].detail

    tool_use_msgs = [r for r in received
                      if isinstance(r, AgentMessage) and r.role == "tool_use"]
    assert len(tool_use_msgs) == 1
    assert "get_video_state" in tool_use_msgs[0].text
    # Task 5 review 후속: tool_name 보존 확인.
    assert tool_use_msgs[0].tool_name == "mcp__kstudio_video__get_video_state"


@pytest.mark.asyncio
async def test_send_message_tool_result_text_only(sdk_mock):
    """UserMessage ToolResultBlock content=str → AgentMessage(role='tool_result')."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _TRB:
        tool_use_id = "toolu_123"
        content = "결과 텍스트"

    class _UM:
        content = [_TRB()]

    async def _r():
        yield _UM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.UserMessage = _UM
    mock_sdk.ToolResultBlock = _TRB

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    tool_results = [r for r in received
                     if isinstance(r, AgentMessage) and r.role == "tool_result"]
    assert len(tool_results) == 1
    assert "결과 텍스트" in tool_results[0].text
    # tool_use_id 보존 — UI 가 어느 tool_use 의 결과인지 매칭 가능.
    assert tool_results[0].tool_name == "toolu_123"


@pytest.mark.asyncio
async def test_send_message_tool_result_with_image(sdk_mock):
    """tool_result content 안에 image dict → image_bytes 추출."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput
    import base64

    mock_sdk, mock_client = sdk_mock

    fake_png = b"\x89PNG\r\n\x1a\nfake"
    b64 = base64.b64encode(fake_png).decode("ascii")

    class _TRB:
        tool_use_id = "toolu_456"
        content = [
            {"type": "image", "data": b64, "mimeType": "image/png"},
            {"type": "text", "text": "이건 프레임이야"},
        ]

    class _UM:
        content = [_TRB()]

    async def _r():
        yield _UM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.UserMessage = _UM
    mock_sdk.ToolResultBlock = _TRB

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    tool_results = [r for r in received
                     if isinstance(r, AgentMessage) and r.role == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0].image_bytes == fake_png
    assert tool_results[0].image_mime == "image/png"
    assert "프레임" in tool_results[0].text


@pytest.mark.asyncio
async def test_send_message_tool_result_empty_content(sdk_mock):
    """content=None / [] 일 때도 안전 — '(빈 결과)' 같은 placeholder."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _TRB:
        tool_use_id = "toolu_789"
        content = None

    class _UM:
        content = [_TRB()]

    async def _r():
        yield _UM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.UserMessage = _UM
    mock_sdk.ToolResultBlock = _TRB

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    tool_results = [r for r in received
                     if isinstance(r, AgentMessage) and r.role == "tool_result"]
    assert len(tool_results) == 1
    # image bytes 없음.
    assert tool_results[0].image_bytes is None
    # text 는 helper 의 "(없음)" placeholder 가 "← " 와 합쳐서 도착.
    assert "없음" in tool_results[0].text


@pytest.mark.asyncio
async def test_send_message_tool_result_empty_list_content(sdk_mock):
    """content=[] (None 과 다른 코드 경로 — isinstance(list) 통과 후 0번 iterate) 도 안전."""
    from screen_recorder.agent.runtime import AgentMessage
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _TRB:
        tool_use_id = "toolu_999"
        content = []

    class _UM:
        content = [_TRB()]

    async def _r():
        yield _UM()
        class _R:
            usage = {}
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.UserMessage = _UM
    mock_sdk.ToolResultBlock = _TRB

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    tool_results = [r for r in received
                     if isinstance(r, AgentMessage) and r.role == "tool_result"]
    assert len(tool_results) == 1
    # 빈 결과 placeholder.
    assert "빈 결과" in tool_results[0].text
    assert tool_results[0].image_bytes is None


@pytest.mark.asyncio
async def test_send_message_done_includes_last_in_from_assistant_msg_usage(sdk_mock):
    """AssistantMessage.usage 의 input_tokens + cache 합산을 last_in 으로 done detail 에."""
    from screen_recorder.agent.runtime import AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _AM:
        content = []
        usage = {
            "input_tokens": 1000,
            "cache_read_input_tokens": 5000,
            "cache_creation_input_tokens": 200,
        }

    class _R:
        usage = {
            "input_tokens": 100,        # SDK 합산 — 사용 안 함
            "output_tokens": 50,
            "cache_read_input_tokens": 5000,
            "cache_creation_input_tokens": 200,
        }

    async def _r():
        yield _AM()
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ResultMessage = _R

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    done_evs = [r for r in received if isinstance(r, AgentEvent) and r.kind == "done"]
    assert len(done_evs) == 1
    # last_in = 1000 + 5000 + 200 = 6200
    assert "last_in=6200" in done_evs[0].detail
    # in (SDK 합산) + out 도 함께 표시.
    assert "in=" in done_evs[0].detail
    assert "out=50" in done_evs[0].detail


@pytest.mark.asyncio
async def test_send_message_done_without_assistant_usage(sdk_mock):
    """AssistantMessage.usage=None 이면 last_in 표시 안 함 — in/out 만."""
    from screen_recorder.agent.runtime import AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _AM:
        content = []
        usage = None

    class _R:
        usage = {"input_tokens": 100, "output_tokens": 50}

    async def _r():
        yield _AM()
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.ResultMessage = _R

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    done_evs = [r for r in received if isinstance(r, AgentEvent) and r.kind == "done"]
    assert len(done_evs) == 1
    assert "last_in" not in done_evs[0].detail   # AM usage 없으니 미표시
    assert "in=100" in done_evs[0].detail
    assert "out=50" in done_evs[0].detail


@pytest.mark.asyncio
async def test_send_message_last_in_uses_last_assistant_message(sdk_mock):
    """도구 호출 시나리오 — 여러 AssistantMessage 가 오면 *마지막* AM 의 usage 만 last_in.

    SDK 흐름: AM_1 (도구 호출) → UserMessage (tool_result) → AM_2 (최종 답변) → ResultMessage.
    last_in 은 AM_2 의 context size 여야 — 사용자에게 표시되는 컨텍스트 % 는 마지막
    API 호출 기준이라 의미가 있음.
    """
    from screen_recorder.agent.runtime import AgentEvent
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    class _AM:
        pass

    class _UM:
        pass

    class _R:
        usage = {"input_tokens": 100, "output_tokens": 50}

    # 두 AM 인스턴스 — 같은 클래스, 다른 usage. isinstance 가 AM 으로 양쪽 다 잡음.
    am1 = _AM()
    am1.content = []
    am1.usage = {"input_tokens": 1000}

    am2 = _AM()
    am2.content = []
    am2.usage = {"input_tokens": 5000}

    um = _UM()
    um.content = []   # 도구 결과 block 없는 빈 UserMessage (단순화).

    async def _r():
        yield am1
        yield um
        yield am2
        yield _R()

    mock_client.receive_response = lambda: _r()
    mock_sdk.AssistantMessage = _AM
    mock_sdk.UserMessage = _UM
    mock_sdk.ResultMessage = _R

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    received: list = []
    await be.send_message(ChatInput(text="hi"), received.append)

    done_evs = [r for r in received if isinstance(r, AgentEvent) and r.kind == "done"]
    assert len(done_evs) == 1
    # 마지막 AM 의 usage (5000) 만 last_in.
    assert "last_in=5000" in done_evs[0].detail
    # 첫 AM 의 1000 은 *없어야* — 덮어쓰기 확인.
    assert "last_in=1000" not in done_evs[0].detail


@pytest.mark.asyncio
async def test_send_message_with_images_uses_multipart(sdk_mock):
    """images 전달 시 client.query 가 async iterable 받음 — multipart content."""
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    sent_payload = []

    async def _query_capture(arg):
        # arg 가 async generator 면 yield 한 dict 모음. 그 외 (str) 도 받음.
        if hasattr(arg, "__aiter__"):
            async for d in arg:
                sent_payload.append(d)
        else:
            sent_payload.append(arg)
    mock_client.query = _query_capture

    # 빈 응답 (text/이미지 검증 만, 응답 흐름은 무관).
    async def _r():
        class _R: usage = {}
        yield _R()
    mock_client.receive_response = lambda: _r()

    png_bytes = b"\x89PNG\r\n\x1a\nfake_png"
    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    await be.send_message(
        ChatInput(text="이 사진 봐", images=[png_bytes]),
        lambda _ev: None,
    )

    assert len(sent_payload) == 1
    payload = sent_payload[0]
    assert payload["type"] == "user"
    content = payload["message"]["content"]
    img_blocks = [b for b in content if b.get("type") == "image"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(img_blocks) == 1
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "이 사진 봐"
    # 이미지 base64 디코드해서 원본 일치.
    import base64
    decoded = base64.b64decode(img_blocks[0]["source"]["data"])
    assert decoded == png_bytes
    assert img_blocks[0]["source"]["media_type"] == "image/png"
    # SDK 스레딩 컨트랙트 — top-level 메시지는 parent_tool_use_id=None.
    assert payload.get("parent_tool_use_id") is None


@pytest.mark.asyncio
async def test_send_message_with_images_empty_text_uses_placeholder(sdk_mock):
    """text='' + images=[...] → placeholder '(첨부 이미지 참고)' 가 들어감."""
    from screen_recorder.agent.backends import ChatInput

    mock_sdk, mock_client = sdk_mock

    sent_payload = []
    async def _query_capture(arg):
        if hasattr(arg, "__aiter__"):
            async for d in arg:
                sent_payload.append(d)
        else:
            sent_payload.append(arg)
    mock_client.query = _query_capture

    async def _r():
        class _R: usage = {}
        yield _R()
    mock_client.receive_response = lambda: _r()

    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    await be.send_message(ChatInput(text="", images=[b"png"]),
                          lambda _: None)

    content = sent_payload[0]["message"]["content"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert text_blocks[0]["text"] == "(첨부 이미지 참고)"


@pytest.mark.asyncio
async def test_send_tool_result_is_noop_for_in_process_mcp(sdk_mock):
    """현재 KStudio 의 모든 MCP 도구는 in-process — send_tool_result 는 no-op stub."""
    be = ClaudeBackend(cwd="/tmp")
    await be.start_session(system_prompt="sys", tools={}, model="sonnet")
    # 예외 없이 그냥 끝나야 함.
    received = []
    await be.send_tool_result("toolu_123", "결과", received.append)
    assert received == []   # emit 안 함.


def test_sniff_image_mime_png():
    from screen_recorder.agent.backends.claude_backend import _sniff_image_mime
    assert _sniff_image_mime(b"\x89PNG\r\n\x1a\nfoo") == "image/png"


def test_sniff_image_mime_jpeg():
    from screen_recorder.agent.backends.claude_backend import _sniff_image_mime
    assert _sniff_image_mime(b"\xff\xd8\xff\xe0_jpeg_body") == "image/jpeg"


def test_sniff_image_mime_gif():
    from screen_recorder.agent.backends.claude_backend import _sniff_image_mime
    assert _sniff_image_mime(b"GIF89a_body") == "image/gif"
    assert _sniff_image_mime(b"GIF87a_body") == "image/gif"


def test_sniff_image_mime_webp():
    from screen_recorder.agent.backends.claude_backend import _sniff_image_mime
    assert _sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBP_body") == "image/webp"


def test_sniff_image_mime_unknown_falls_back_to_png():
    from screen_recorder.agent.backends.claude_backend import _sniff_image_mime
    assert _sniff_image_mime(b"\x00\x01\x02\x03random") == "image/png"
    assert _sniff_image_mime(b"") == "image/png"
