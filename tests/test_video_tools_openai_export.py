"""VideoTools.openai_tools_and_handlers — KStudio 도구 19개 OpenAI 형식 노출."""
from __future__ import annotations

from unittest.mock import MagicMock


def _make_video_tools():
    """가짜 adapter 로 VideoTools 인스턴스 생성."""
    from screen_recorder.agent.tools import VideoTools

    adapter = MagicMock()
    adapter.has_active_video = MagicMock(return_value=False)
    return VideoTools(adapter=adapter)


def test_openai_tools_returns_list_of_function_dicts():
    """openai_tools_and_handlers — (openai_tools, handlers) 튜플."""
    vt = _make_video_tools()
    openai_tools, handlers = vt.openai_tools_and_handlers()
    assert isinstance(openai_tools, list)
    assert isinstance(handlers, dict)
    # 19개 도구 (transcript 제외 = 17 — vt fixture 가 transcript_ctx 없음).
    assert len(openai_tools) >= 17


def test_openai_tools_each_has_function_wrapper():
    """각 항목이 OpenAI function calling 형식."""
    vt = _make_video_tools()
    openai_tools, _ = vt.openai_tools_and_handlers()
    for t in openai_tools:
        assert t["type"] == "function"
        fn = t["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        # prefix 제거된 이름.
        assert not fn["name"].startswith("mcp__")


def test_openai_tools_handlers_match_names():
    """handlers dict 의 키 = openai_tools name 과 일대일."""
    vt = _make_video_tools()
    openai_tools, handlers = vt.openai_tools_and_handlers()
    tool_names = {t["function"]["name"] for t in openai_tools}
    handler_names = set(handlers.keys())
    assert tool_names == handler_names


def test_handler_is_callable_async():
    """각 핸들러는 호출 가능 + async (await 가능)."""
    import asyncio
    vt = _make_video_tools()
    _, handlers = vt.openai_tools_and_handlers()
    # 임의 하나 — get_video_state 가 항상 있음.
    h = handlers.get("get_video_state")
    assert h is not None
    # adapter.has_active_video = False 이므로 no_active_video 응답.
    result = asyncio.run(h({}))
    assert isinstance(result, dict)
