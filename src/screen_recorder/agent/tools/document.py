"""문서(Markdown) 도구 — 활성 문서 읽기 + 직접 수정 (Ctrl+Z 취소 가능).

영상 도구와 달리 plan gate 없이 *즉시 적용* (사용자 선택 2026-05-29: "바로 수정/Ctrl+Z").
읽기는 어댑터에서 직접(영상 read 도구와 동일 패턴), 수정은 QTextDocument 를 UI 스레드에서
건드려야 하므로 on_edit 콜백 + future 로 마샬링 (apply_proposals 와 동일 패턴).

수정은 cursor.beginEditBlock 한 묶음으로 적용돼 Ctrl+Z 한 번에 되돌릴 수 있다.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Callable, Optional

from claude_agent_sdk import tool

from ._response import error_result, text_result

_log = logging.getLogger(__name__)

DOCUMENT_TOOL_NAMES = (
    "get_document_state",
    "read_document",
    "replace_document",
    "find_replace_in_document",
)

# (action: dict, future) — UI 스레드가 적용 후 future.set_result(dict) 로 해결.
DocumentEditCallback = Callable[[dict, concurrent.futures.Future], None]


def _no_active_document() -> dict:
    return error_result(
        "열려 있는 문서가 없습니다. 사용자가 문서 모드에서 .md 문서를 먼저 열어야 합니다."
    )


async def _dispatch_edit(on_edit, action: dict) -> dict:
    """on_edit 콜백으로 UI 스레드에 편집 요청 → future 결과 await."""
    fut: concurrent.futures.Future = concurrent.futures.Future()
    try:
        on_edit(action, fut)
    except Exception as exc:  # 콜백 자체 실패
        _log.exception("document edit dispatch 실패")
        return error_result(f"편집 디스패치 실패: {exc}")
    try:
        result = await asyncio.wrap_future(fut)
    except Exception as exc:
        _log.exception("document edit future 실패")
        return error_result(f"편집 적용 실패: {exc}")
    return text_result(result)


def make_document_tools(adapter, on_edit: Optional[DocumentEditCallback]) -> list:
    @tool(
        "get_document_state",
        "현재 활성 Markdown 문서의 메타데이터 — 경로, 글자 수, 줄 수, 미저장 여부, "
        "앞부분 미리보기(500자). 문서 작업 시작 시 가장 먼저 호출해 무엇이 열려 있는지 확인.",
        {},
    )
    async def get_document_state(args: dict) -> dict:
        if not adapter.has_active_document():
            return _no_active_document()
        text = adapter.read_text() or ""
        return text_result({
            "path": adapter.document_path(),
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
            "is_dirty": adapter.is_dirty(),
            "preview": text[:500],
        })

    @tool(
        "read_document",
        "현재 활성 문서의 *전체* 텍스트를 그대로 반환. 수정·요약·질문 전에 내용 파악용. "
        "긴 문서면 find_replace_in_document 로 부분 수정하는 게 토큰 효율적.",
        {},
    )
    async def read_document(args: dict) -> dict:
        if not adapter.has_active_document():
            return _no_active_document()
        return text_result({"text": adapter.read_text() or ""})

    @tool(
        "replace_document",
        "현재 문서의 *전체* 내용을 content 로 교체. 큰 구조 변경/재작성에 사용. "
        "작은 수정엔 find_replace_in_document 가 더 안전·효율적. "
        "적용은 즉시 (Ctrl+Z 한 번으로 되돌릴 수 있음). 적용 전 사용자에게 무엇을 바꿀지 한 줄 안내 권장.",
        {"content": str},
    )
    async def replace_document(args: dict) -> dict:
        if not adapter.has_active_document():
            return _no_active_document()
        if on_edit is None:
            return error_result("문서 편집 콜백 미설정 — 런타임 wiring 점검 필요.")
        content = args.get("content")
        if content is None:
            return error_result("content 인자 필수.")
        return await _dispatch_edit(on_edit, {"op": "replace", "content": str(content)})

    @tool(
        "find_replace_in_document",
        "현재 문서에서 find 문자열을 replace 로 치환. count=0(기본)이면 전부, N 이면 처음 N 개만. "
        "find 는 정확히 일치하는 텍스트여야 함(정규식 아님). 매치가 0 이면 아무것도 바꾸지 않고 "
        "n_replaced=0 반환 — 그 경우 read_document 로 실제 내용 확인 후 재시도. "
        "적용은 즉시 (Ctrl+Z 로 되돌림).",
        {"find": str, "replace": str, "count": int},
    )
    async def find_replace_in_document(args: dict) -> dict:
        if not adapter.has_active_document():
            return _no_active_document()
        if on_edit is None:
            return error_result("문서 편집 콜백 미설정 — 런타임 wiring 점검 필요.")
        find = args.get("find")
        if not find:
            return error_result("find 인자 필수 (빈 문자열 불가).")
        replace = args.get("replace", "")
        count = int(args.get("count") or 0)
        return await _dispatch_edit(on_edit, {
            "op": "find_replace", "find": str(find),
            "replace": str(replace), "count": count,
        })

    return [get_document_state, read_document, replace_document, find_replace_in_document]
