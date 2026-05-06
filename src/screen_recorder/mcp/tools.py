"""KStudio MCP 도구 정의 — HTTP 핸들러가 라우팅으로 부르는 함수들.

각 도구는 dict (요청 파라미터) → dict (응답) 의 단순 함수. UI 스레드에서 실행돼야
하므로 호출 측이 `UIDispatcher` 로 마샬링한다.

read-only 도구는 즉시 dict 반환. 명령(write) 도구는 Stage 4 에서 추가 예정 —
권한 모델 + request_id 기반 async 패턴.

새 도구 추가:
1. 핸들러 함수 작성 — `(window, params: dict) -> dict`.
2. `TOOLS` 레지스트리에 이름→함수 등록.
3. `list_tools()` 의 메타데이터 dict 추가 (LLM 이 도구를 이해하는 근거).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from screen_recorder.core.settings import default_image_dir, default_video_dir


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


def list_library(window, params: dict) -> dict:
    """라이브러리(이번 세션 동안 캡처/열린 항목) 목록.

    파라미터:
    - `kind` (str | null, 선택): "image" / "video" / null(=전체).

    응답:
    - `entries` (list): 각 항목 dict — id, kind, display_name, path, source_label,
      created_at(ISO 8601), duration_ms, origin, has_thumbnail, width, height.
    """
    from screen_recorder.ui.library_model import EntryKind

    raw_kind = params.get("kind")
    if raw_kind == "image":
        filt = EntryKind.IMAGE
    elif raw_kind == "video":
        filt = EntryKind.VIDEO
    else:
        filt = None

    out = []
    for e in window.library_model.entries(filt):
        out.append({
            "id": e.id,
            "kind": e.kind.value,
            "display_name": e.display_name,
            "path": str(e.path) if e.path is not None else None,
            "source_label": e.source_label,
            "created_at": e.created_at.isoformat(),
            "duration_ms": e.duration_ms,
            "origin": e.origin,
            "has_thumbnail": not e.thumbnail.isNull(),
            "width": e.thumbnail.width() if not e.thumbnail.isNull() else None,
            "height": e.thumbnail.height() if not e.thumbnail.isNull() else None,
        })
    return {"entries": out, "total": len(out)}


def list_tabs(window, params: dict) -> dict:
    """현재 열린 탭 목록 + 활성 탭 인덱스.

    응답:
    - `tabs` (list): 각 탭 dict — index, kind("image"|"video"), entry_id, title,
      modified, has_image (이미지 탭만 의미 있음).
    - `active_index` (int): 현재 포커스된 탭. 비어있으면 -1.
    """
    tabs = []
    for i in range(window.tab_area.count()):
        if not window.tab_area.isTabVisible(i):
            continue
        widget = window.tab_area.widget(i)
        title = window.tab_area.tabText(i)
        # 어떤 종류의 탭인지 — EditTab 은 이미지, VideoTab 은 영상.
        kind = "image" if hasattr(widget, "stack") else "video"
        modified = False
        if hasattr(widget, "undo_stack"):
            try:
                modified = not widget.undo_stack.isClean()
            except Exception:   # noqa: BLE001
                modified = False
        # 활성 탭의 entry id 도 포함 — current 탭만 정확히 알 수 있음
        entry_id = None
        if i == window.tab_area.currentIndex():
            entry_id = window.tab_area.current_entry_id()
        tabs.append({
            "index": i,
            "kind": kind,
            "entry_id": entry_id,
            "title": title,
            "modified": modified,
        })
    return {
        "tabs": tabs,
        "active_index": window.tab_area.currentIndex(),
        "total": len(tabs),
    }


def get_current_mode(window, params: dict) -> dict:
    """현재 앱 모드 — "image" 또는 "video"."""
    from screen_recorder.ui.mode_controller import AppMode
    mode = window.mode_controller.mode()
    return {
        "mode": "video" if mode is AppMode.VIDEO else "image",
    }


def get_save_dirs(window, params: dict) -> dict:
    """이미지/영상 저장 폴더 절대 경로 + 환경설정의 파일명 패턴.

    응답: image_dir, video_dir, image_filename_pattern, video_filename_pattern,
    image_format ("png"|"jpg"|"webp").
    """
    s = window.app_settings
    img_dir = s.screenshot.save_dir or str(default_image_dir())
    vid_dir = s.general.output_dir or str(default_video_dir())
    return {
        "image_dir": str(Path(img_dir).resolve()),
        "video_dir": str(Path(vid_dir).resolve()),
        "image_filename_pattern": s.screenshot.filename_pattern,
        "video_filename_pattern": s.general.filename_pattern,
        "image_format": s.screenshot.format,
    }


def get_settings_summary(window, params: dict) -> dict:
    """KStudio 핵심 설정 스냅샷 — LLM 이 사용자 환경을 이해하기 위한 메타.

    민감 정보(MCP 토큰 등) 는 노출 X. 토글/패턴/폴더 같은 사용자 의도만.
    """
    s = window.app_settings
    img_dir = s.screenshot.save_dir or str(default_image_dir())
    vid_dir = s.general.output_dir or str(default_video_dir())
    return {
        "image_dir": str(Path(img_dir).resolve()),
        "video_dir": str(Path(vid_dir).resolve()),
        "image_filename_pattern": s.screenshot.filename_pattern,
        "video_filename_pattern": s.general.filename_pattern,
        "image_format": s.screenshot.format,
        "video_codec": s.video.codec,
        "video_fps": s.video.fps,
        "video_container": s.video.container,
        "gif_fps": s.gif.fps,
        "gif_colors": s.gif.colors,
        "minimize_to_tray": s.preferences.minimize_to_tray,
        "language": s.preferences.language,
        "current_mode": (
            "video"
            if window.mode_controller.mode().value == "video"
            else "image"
        ),
        "intercept_system_keys": s.hotkey.intercept_system_keys,
    }


# 도구 레지스트리 — 이름으로 조회. 새 도구 추가 시 여기 등록.
TOOLS: dict[str, Callable[[Any, dict], dict]] = {
    "get_current_image_path": get_current_image_path,
    "list_library": list_library,
    "list_tabs": list_tabs,
    "get_current_mode": get_current_mode,
    "get_save_dirs": get_save_dirs,
    "get_settings_summary": get_settings_summary,
}


def list_tools() -> list[dict]:
    """등록된 도구 메타 리스트 — `/mcp/v1/tools` 응답에 사용.

    각 dict 는 `name`, `description`, `params` (JSON Schema-like). LLM 이 이 메타를
    보고 어떤 인자로 호출할지 결정한다.
    """
    return [
        {
            "name": "get_current_image_path",
            "description": "현재 활성 이미지 탭의 디스크 경로와 픽셀 크기 메타.",
            "params": {},
        },
        {
            "name": "list_library",
            "description": "이번 세션의 라이브러리(스크린샷·영상) 목록.",
            "params": {
                "kind": {
                    "type": "string",
                    "enum": ["image", "video"],
                    "description": "필터. 생략하면 전체.",
                    "required": False,
                },
            },
        },
        {
            "name": "list_tabs",
            "description": "현재 열린 탭 목록 + 활성 탭 인덱스.",
            "params": {},
        },
        {
            "name": "get_current_mode",
            "description": '현재 앱 모드 ("image" 또는 "video").',
            "params": {},
        },
        {
            "name": "get_save_dirs",
            "description": "이미지/영상 저장 폴더 절대 경로 + 파일명 패턴.",
            "params": {},
        },
        {
            "name": "get_settings_summary",
            "description": "KStudio 핵심 설정 스냅샷 (민감정보 제외).",
            "params": {},
        },
    ]
