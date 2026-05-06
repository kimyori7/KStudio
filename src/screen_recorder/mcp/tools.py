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


# ===================== 명령 도구 (sync) =====================


def open_image_path(window, params: dict) -> dict:
    """디스크 파일을 KStudio 에서 새 탭으로 연다.

    파라미터:
    - `path` (str, required): 절대 경로. 지원 확장자 .png/.jpg/.jpeg/.webp/.bmp/.kstudio.

    응답: success(bool), opened_path(str|null), error(str|null).
    """
    path_str = params.get("path") or ""
    if not path_str:
        return {"success": False, "error": "path 파라미터 필요"}
    p = Path(path_str)
    if not p.is_absolute():
        return {"success": False, "error": "절대 경로 필요"}
    if not p.exists():
        return {"success": False, "error": f"파일 없음: {p}"}
    if p.suffix.lower() not in window.IMAGE_EXTS:
        return {
            "success": False,
            "error": f"지원하지 않는 확장자: {p.suffix} (지원: {sorted(window.IMAGE_EXTS)})",
        }
    try:
        window._open_image_path(p)
        return {"success": True, "opened_path": str(p), "error": None}
    except Exception as e:   # noqa: BLE001
        return {"success": False, "error": str(e)}


def save_current_tab(window, params: dict) -> dict:
    """현재 활성 이미지 탭을 디스크에 저장. 이미 저장된 탭은 같은 경로에 덮어쓰기.

    응답: success(bool), saved_path(str|null), error(str|null).
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}
    try:
        window._save_current_screenshot()
    except Exception as e:   # noqa: BLE001
        return {"success": False, "error": str(e)}
    entry = window._entry_for_current_tab()
    saved = str(entry.path) if (entry is not None and entry.path is not None) else None
    return {"success": True, "saved_path": saved, "error": None}


def set_mode(window, params: dict) -> dict:
    """앱 모드 전환 — "image" 또는 "video".

    파라미터: `mode` (str, required).
    응답: success(bool), current_mode(str), error(str|null).
    """
    from screen_recorder.ui.mode_controller import AppMode
    requested = (params.get("mode") or "").lower()
    if requested == "image":
        target = AppMode.IMAGE
    elif requested == "video":
        target = AppMode.VIDEO
    else:
        return {
            "success": False, "current_mode": None,
            "error": f"mode 는 'image' 또는 'video' 여야 함 (받음: {requested!r})",
        }
    try:
        window.mode_controller.set_mode(target)
        return {
            "success": True,
            "current_mode": "video" if target is AppMode.VIDEO else "image",
            "error": None,
        }
    except Exception as e:   # noqa: BLE001
        return {"success": False, "current_mode": None, "error": str(e)}


def resize_image(window, params: dict) -> dict:
    """현재 이미지 탭을 LANCZOS 로 리사이즈해 새 탭 생성. 원본 보존.

    파라미터:
    - `target_w` (int, required): 목표 가로 픽셀.
    - `target_h` (int, required): 목표 세로 픽셀.

    응답: success, saved_path(저장된 결과 PNG), width, height, error.

    고품질 AI 업스케일은 별도 도구 `ai_upscale` 를 사용. 본 도구는 빠른 LANCZOS만.
    """
    from screen_recorder.encode.scale import (
        scale_qimage, resolve_scaled_path, save_scaled,
    )
    from screen_recorder.core.settings import default_image_dir

    try:
        tw = int(params.get("target_w"))
        th = int(params.get("target_h"))
    except (TypeError, ValueError):
        return {"success": False, "error": "target_w / target_h 정수 필요"}
    if tw < 1 or th < 1 or tw > 16384 or th > 16384:
        return {"success": False, "error": "픽셀 범위는 1~16384"}

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}
    img = tab.image()
    if img.isNull():
        return {"success": False, "error": "탭 이미지 비어있음"}

    entry = window._entry_for_current_tab()
    if entry is not None and entry.path is not None:
        src_for_naming = entry.path
    else:
        save_dir = Path(window.app_settings.screenshot.save_dir or default_image_dir())
        save_dir.mkdir(parents=True, exist_ok=True)
        display = entry.display_name if entry is not None else "image"
        src_for_naming = save_dir / f"{display}.png"

    try:
        out = scale_qimage(img, tw, th)
        dst = resolve_scaled_path(src_for_naming, tw, th)
        dst.parent.mkdir(parents=True, exist_ok=True)
        save_scaled(out, dst)
        window._open_image_path(dst)
    except Exception as e:   # noqa: BLE001
        return {"success": False, "error": str(e)}
    return {
        "success": True,
        "saved_path": str(dst), "width": tw, "height": th,
        "error": None,
    }


# ===================== 명령 도구 (async via request_id) =====================


def ai_upscale(window, params: dict) -> dict:
    """Real-ESRGAN x4 AI 업스케일 → LANCZOS 로 정확한 목표 픽셀에 맞춤. 비동기.

    파라미터:
    - `target_w` (int, required), `target_h` (int, required).

    수십 초 ~ 수 분 걸릴 수 있어 즉시 request_id 만 반환. LLM 은
    `get_request_status(request_id=...)` 로 폴링한다.
    """
    from screen_recorder.encode import upscale as _up
    from screen_recorder.encode.scale import (
        scale_qimage, resolve_scaled_path, save_scaled,
    )
    from screen_recorder.core.settings import default_image_dir

    try:
        tw = int(params.get("target_w"))
        th = int(params.get("target_h"))
    except (TypeError, ValueError):
        return {"success": False, "error": "target_w / target_h 정수 필요"}

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}
    img = tab.image()
    if img.isNull():
        return {"success": False, "error": "탭 이미지 비어있음"}
    if tw <= img.width() and th <= img.height():
        return {
            "success": False,
            "error": "AI 업스케일은 업스케일에만 의미 있음 (다운스케일은 resize_image 사용)",
        }

    rid = window._mcp_request_store.create("ai_upscale")

    entry = window._entry_for_current_tab()
    if entry is not None and entry.path is not None:
        src_for_naming = entry.path
    else:
        save_dir = Path(window.app_settings.screenshot.save_dir or default_image_dir())
        save_dir.mkdir(parents=True, exist_ok=True)
        display = entry.display_name if entry is not None else "image"
        src_for_naming = save_dir / f"{display}.png"

    emitter = _up.start_upscale_async(img, _up.DEFAULT_MODEL_ID)

    def _on_finished(upscaled):
        try:
            if upscaled.width() != tw or upscaled.height() != th:
                final = scale_qimage(upscaled, tw, th)
            else:
                final = upscaled
            dst = resolve_scaled_path(src_for_naming, tw, th)
            dst.parent.mkdir(parents=True, exist_ok=True)
            save_scaled(final, dst)
            window._open_image_path(dst)
            window._mcp_request_store.complete(rid, {
                "saved_path": str(dst),
                "width": tw, "height": th,
            })
        except Exception as e:   # noqa: BLE001
            window._mcp_request_store.fail(rid, str(e))

    def _on_failed(msg: str):
        window._mcp_request_store.fail(rid, msg)

    emitter.finished.connect(_on_finished)
    emitter.failed.connect(_on_failed)

    return {"success": True, "request_id": rid, "status": "pending"}


def remove_background(window, params: dict) -> dict:
    """현재 활성 이미지 레이어에 자동 누끼(rembg) 적용. 비동기.

    파라미터:
    - `model` (str, optional): rembg 모델 id (기본은 settings.annotation.bg_removal_model
      또는 "u2net").

    응답: request_id 즉시 반환. 결과는 `get_request_status` 로 폴링.
    """
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.background_removal import BackgroundRemovalCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}
    active = tab.stack.active_layer()
    if not isinstance(active, ImageLayer):
        window._ensure_active_image_layer(tab)
        active = tab.stack.active_layer()
        if not isinstance(active, ImageLayer):
            return {"success": False, "error": "이미지 레이어가 없음"}

    model = params.get("model") or window.app_settings.annotation.bg_removal_model or "u2net"
    rid = window._mcp_request_store.create("remove_background")
    cmd = BackgroundRemovalCommand(tab.stack, layer_id=active.id, model_name=model)

    def _on_done(success: bool):
        if success:
            tab.undo_stack.push(cmd)
            window._mcp_request_store.complete(rid, {
                "model": model, "applied": True,
            })

    def _on_failed(msg: str):
        window._mcp_request_store.fail(rid, msg)

    cmd.finished.connect(_on_done)
    cmd.failed.connect(_on_failed)
    cmd.run_async()
    return {"success": True, "request_id": rid, "status": "pending"}


def get_request_status(window, params: dict) -> dict:
    """진동벨 폴링 — async 도구가 발급한 request_id 의 현재 상태 조회.

    파라미터: `request_id` (str, required).
    응답: PendingRequest.to_dict() 그대로.
    """
    rid = params.get("request_id") or ""
    if not rid:
        return {"error": "request_id 필요"}
    req = window._mcp_request_store.get(rid)
    if req is None:
        return {"error": f"unknown request_id: {rid}"}
    return req.to_dict()


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
    # read-only
    "get_current_image_path": get_current_image_path,
    "list_library": list_library,
    "list_tabs": list_tabs,
    "get_current_mode": get_current_mode,
    "get_save_dirs": get_save_dirs,
    "get_settings_summary": get_settings_summary,
    # commands (sync)
    "open_image_path": open_image_path,
    "save_current_tab": save_current_tab,
    "set_mode": set_mode,
    "resize_image": resize_image,
    # commands (async via request_id)
    "ai_upscale": ai_upscale,
    "remove_background": remove_background,
    "get_request_status": get_request_status,
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
        {
            "name": "open_image_path",
            "description": "디스크 파일을 KStudio 새 탭으로 연다.",
            "params": {
                "path": {"type": "string", "required": True,
                         "description": "절대 경로 (.png/.jpg/.webp/.bmp/.kstudio)"},
            },
        },
        {
            "name": "save_current_tab",
            "description": "현재 활성 이미지 탭을 디스크에 저장.",
            "params": {},
        },
        {
            "name": "set_mode",
            "description": "앱 모드 전환 (image | video).",
            "params": {
                "mode": {"type": "string", "enum": ["image", "video"],
                         "required": True},
            },
        },
        {
            "name": "resize_image",
            "description": "현재 이미지 탭을 LANCZOS 로 리사이즈해 새 PNG 생성. 고품질 업스케일은 ai_upscale 사용.",
            "params": {
                "target_w": {"type": "integer", "required": True,
                             "description": "1~16384"},
                "target_h": {"type": "integer", "required": True,
                             "description": "1~16384"},
            },
        },
        {
            "name": "ai_upscale",
            "description": "Real-ESRGAN x4 AI 업스케일. 비동기 — request_id 반환, get_request_status 로 폴링.",
            "params": {
                "target_w": {"type": "integer", "required": True},
                "target_h": {"type": "integer", "required": True},
            },
        },
        {
            "name": "remove_background",
            "description": "현재 이미지의 배경 자동 제거(rembg). 비동기 — request_id 반환.",
            "params": {
                "model": {"type": "string", "required": False,
                          "description": "rembg 모델 id (기본은 사용자 설정값)"},
            },
        },
        {
            "name": "get_request_status",
            "description": "비동기 도구가 발급한 request_id 의 현재 상태/결과 조회.",
            "params": {
                "request_id": {"type": "string", "required": True},
            },
        },
    ]
