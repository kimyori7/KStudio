"""에이전트 문서(Markdown) 도구 — 읽기 + 직접 수정(콜백 디스패치)."""
from __future__ import annotations

import pytest

from screen_recorder.agent.tools.document import (
    DOCUMENT_TOOL_NAMES, make_document_tools,
)


class _FakeDocAdapter:
    def __init__(self, text="hello\nworld", path="C:/d/a.md", dirty=False, active=True):
        self._t, self._p, self._d, self._a = text, path, dirty, active

    def has_active_document(self): return self._a
    def read_text(self): return self._t if self._a else None
    def document_path(self): return self._p if self._a else None
    def is_dirty(self): return self._d


def _handlers(adapter, on_edit=None):
    return {t.name: t.handler for t in make_document_tools(adapter, on_edit)}


def test_document_tool_names():
    assert DOCUMENT_TOOL_NAMES == (
        "get_document_state", "read_document",
        "replace_document", "find_replace_in_document",
    )


async def test_read_document_returns_full_text():
    h = _handlers(_FakeDocAdapter(text="# 제목\n본문"))
    res = await h["read_document"]({})
    assert "# 제목" in res["content"][0]["text"]


async def test_get_document_state_metadata():
    h = _handlers(_FakeDocAdapter(text="a\nb\nc", path="C:/d/x.md", dirty=True))
    txt = await h["get_document_state"]({})
    body = txt["content"][0]["text"]
    assert "x.md" in body and "line_count" in body and "char_count" in body


async def test_no_active_document_is_error():
    h = _handlers(_FakeDocAdapter(active=False))
    res = await h["read_document"]({})
    assert res.get("isError") is True


async def test_replace_document_dispatches_edit():
    captured = {}

    def on_edit(action, fut):
        captured["action"] = action
        fut.set_result({"ok": True, "op": "replace", "char_count": len(action["content"])})

    h = _handlers(_FakeDocAdapter(), on_edit)
    res = await h["replace_document"]({"content": "new text"})
    assert captured["action"]["op"] == "replace"
    assert captured["action"]["content"] == "new text"
    assert '"ok": true' in res["content"][0]["text"]


async def test_find_replace_dispatches_args():
    seen = {}

    def on_edit(action, fut):
        seen["action"] = action
        fut.set_result({"ok": True, "op": "find_replace", "n_replaced": 2})

    h = _handlers(_FakeDocAdapter(), on_edit)
    res = await h["find_replace_in_document"]({"find": "a", "replace": "b", "count": 0})
    assert seen["action"] == {"op": "find_replace", "find": "a", "replace": "b", "count": 0}
    assert '"n_replaced": 2' in res["content"][0]["text"]


async def test_edit_without_callback_errors():
    h = _handlers(_FakeDocAdapter(), None)
    res = await h["replace_document"]({"content": "x"})
    assert res.get("isError") is True


async def test_find_replace_requires_find():
    h = _handlers(_FakeDocAdapter(), lambda a, f: f.set_result({}))
    res = await h["find_replace_in_document"]({"find": "", "replace": "x"})
    assert res.get("isError") is True


def test_videotools_exposes_document_tools_only_with_adapter():
    from screen_recorder.agent.tools import VideoTools

    class _V:
        def has_active_video(self): return False
        def source_path(self): return None
        def duration_ms(self): return 0
        def position_ms(self): return 0
        def sidecar(self): return None

    with_doc = VideoTools(_V(), document_adapter=_FakeDocAdapter())
    names = with_doc.tool_names()
    assert any(n.endswith("__read_document") for n in names)
    assert any(n.endswith("__find_replace_in_document") for n in names)

    without_doc = VideoTools(_V())
    assert not any(n.endswith("__read_document") for n in without_doc.tool_names())
