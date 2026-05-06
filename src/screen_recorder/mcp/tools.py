"""KStudio MCP 도구 정의 — HTTP 핸들러가 라우팅으로 부르는 함수들.

각 도구는 dict (요청 파라미터) → dict (응답) 의 단순 함수. UI 스레드에서 실행돼야
하므로 호출 측이 `UIDispatcher` 로 마샬링한다.

Stage 1: read-only 도구 1개만 (`get_current_image_path`). 새 도구를 추가할 때는
`TOOLS` 레지스트리에 등록 + 핸들러 함수 추가. 모든 도구는:
- 메인 윈도우 인스턴스를 인자로 받는다 (UI 스레드 컨텍스트).
- 부작용 없는(read-only) 도구는 즉시 dict 반환.
- 명령(write) 도구는 후속 단계에서 추가 — 권한 모델 + async 패턴 결정 후.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable


def get_current_image_path(window, params: dict) -> dict:
    """현재 활성 이미지 탭의 디스크 경로(있으면) 와 라이브러리 메타.

    응답:
    - `has_tab` (bool): 현재 활성 이미지 탭이 있는지.
    - `path` (str | null): 디스크 파일이면 절대 경로, 미저장(캡처 직후) 이면 null.
    - `display_name` (str | null): 라이브러리에 표시되는 이름 (확장자 제외).
    - `width` / `height` (int | null): 합성 결과 픽셀 크기.
    - `is_modified` (bool | null): 미저장 변경 여부 (탭의 undo stack 기준).
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"has_tab": False, "path": None, "display_name": None,
                "width": None, "height": None, "is_modified": None}
    entry = window._entry_for_current_tab()
    img = tab.image()
    return {
        "has_tab": True,
        "path": str(entry.path) if (entry is not None and entry.path is not None) else None,
        "display_name": entry.display_name if entry is not None else None,
        "width": img.width() if not img.isNull() else None,
        "height": img.height() if not img.isNull() else None,
        "is_modified": (not tab.undo_stack.isClean()) if hasattr(tab, "undo_stack") else None,
    }


# 도구 레지스트리 — 이름으로 조회. 새 도구 추가 시 여기 등록.
TOOLS: dict[str, Callable[[Any, dict], dict]] = {
    "get_current_image_path": get_current_image_path,
}


def list_tools() -> list[dict]:
    """등록된 도구 메타 리스트 — `/mcp/v1/tools` 응답에 사용."""
    return [
        {
            "name": "get_current_image_path",
            "description": "현재 활성 이미지 탭의 디스크 경로와 메타데이터를 반환한다.",
            "params": {},   # Stage 1 도구는 파라미터 없음
        },
    ]
