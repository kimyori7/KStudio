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


# ===================== 그리기 도구 =====================


def _parse_color(color_str: str | None) -> "QColor | None":
    """hex 색상 문자열 파싱. 실패하면 None."""
    if not color_str:
        return None
    from PySide6.QtGui import QColor
    s = color_str.lstrip("#")
    if len(s) == 6:
        try:
            return QColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            return None
    return None


def draw_rect(window, params: dict) -> dict:
    """현재 이미지 탭에 사각형 주석 추가.

    파라미터:
    - `x1`, `y1`, `x2`, `y2` (number, required): 사각형 두 꼭짓점 좌표 (픽셀).
    - `color` (str, optional): hex 색상 "#RRGGBB". 기본 빨강 #FF0000.
    - `thickness` (int, optional): 두께 step (0~4). 기본 1.

    응답: success, index (주석 인덱스), error.
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor
    from image_editor.items.rect import RectAnnotationItem
    from image_editor.commands import AddAnnotationCommand
    from screen_recorder.ui.main_window import MainWindow

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        x1 = float(params.get("x1"))
        y1 = float(params.get("y1"))
        x2 = float(params.get("x2"))
        y2 = float(params.get("y2"))
    except (TypeError, ValueError):
        return {"success": False, "error": "x1, y1, x2, y2 좌표 필요"}

    color = _parse_color(params.get("color")) or QColor(255, 0, 0)
    thickness = int(params.get("thickness") or 1)
    thickness = max(0, min(4, thickness))

    layer = MainWindow._ensure_annotation_layer(tab)
    scene = layer.scene
    rect = QRectF(x1, y1, x2 - x1, y2 - y1).normalized()
    item = RectAnnotationItem(rect, color, thickness)

    cmd = AddAnnotationCommand(scene, item)
    tab.undo_stack.push(cmd)

    return {"success": True, "index": len(scene.annotations()) - 1, "error": None}


def draw_arrow(window, params: dict) -> dict:
    """현재 이미지 탭에 화살표 주석 추가.

    파라미터:
    - `x1`, `y1` (number, required): 시작점 좌표.
    - `x2`, `y2` (number, required): 끝점 (화살표 머리) 좌표.
    - `color` (str, optional): hex 색상. 기본 빨강.
    - `thickness` (int, optional): 두께 step (0~4). 기본 1.

    응답: success, index, error.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor
    from image_editor.items.arrow import ArrowAnnotationItem
    from image_editor.commands import AddAnnotationCommand
    from screen_recorder.ui.main_window import MainWindow

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        x1 = float(params.get("x1"))
        y1 = float(params.get("y1"))
        x2 = float(params.get("x2"))
        y2 = float(params.get("y2"))
    except (TypeError, ValueError):
        return {"success": False, "error": "x1, y1, x2, y2 좌표 필요"}

    color = _parse_color(params.get("color")) or QColor(255, 0, 0)
    thickness = int(params.get("thickness") or 1)
    thickness = max(0, min(4, thickness))

    layer = MainWindow._ensure_annotation_layer(tab)
    scene = layer.scene
    item = ArrowAnnotationItem(QPointF(x1, y1), QPointF(x2, y2), color, thickness)

    cmd = AddAnnotationCommand(scene, item)
    tab.undo_stack.push(cmd)

    return {"success": True, "index": len(scene.annotations()) - 1, "error": None}


def add_text(window, params: dict) -> dict:
    """현재 이미지 탭에 텍스트 주석 추가.

    파라미터:
    - `x`, `y` (number, required): 텍스트 위치 좌표.
    - `text` (str, required): 표시할 텍스트.
    - `color` (str, optional): hex 색상. 기본 빨강.

    응답: success, index, error.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor
    from image_editor.items.text import TextAnnotationItem
    from image_editor.commands import AddAnnotationCommand
    from screen_recorder.ui.main_window import MainWindow

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        x = float(params.get("x"))
        y = float(params.get("y"))
    except (TypeError, ValueError):
        return {"success": False, "error": "x, y 좌표 필요"}

    text = params.get("text") or ""
    if not text:
        return {"success": False, "error": "text 파라미터 필요"}

    color = _parse_color(params.get("color")) or QColor(255, 0, 0)

    layer = MainWindow._ensure_annotation_layer(tab)
    scene = layer.scene
    item = TextAnnotationItem(text, color)
    item.setPos(QPointF(x, y))

    cmd = AddAnnotationCommand(scene, item)
    tab.undo_stack.push(cmd)

    return {"success": True, "index": len(scene.annotations()) - 1, "error": None}


def list_annotations(window, params: dict) -> dict:
    """현재 이미지 탭의 주석 목록 조회.

    응답:
    - `annotations` (list): 각 주석 dict — index, type("rect"|"arrow"|"text"),
      bounds(x, y, width, height), color(hex).
    - `total` (int): 주석 개수.
    """
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.items.rect import RectAnnotationItem
    from image_editor.items.arrow import ArrowAnnotationItem
    from image_editor.items.text import TextAnnotationItem

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"annotations": [], "total": 0}

    # AnnotationLayer 찾기
    ann_layer = None
    for layer in tab.stack.layers:
        if isinstance(layer, AnnotationLayer):
            ann_layer = layer
            break
    if ann_layer is None:
        return {"annotations": [], "total": 0}

    out = []
    for i, item in enumerate(ann_layer.scene.annotations()):
        bounds = item.sceneBoundingRect()
        color_hex = None
        item_type = "unknown"

        if isinstance(item, RectAnnotationItem):
            item_type = "rect"
            color_hex = item.color().name()
        elif isinstance(item, ArrowAnnotationItem):
            item_type = "arrow"
            color_hex = item.color().name()
        elif isinstance(item, TextAnnotationItem):
            item_type = "text"
            color_hex = item.color().name()

        out.append({
            "index": i,
            "type": item_type,
            "bounds": {
                "x": bounds.x(),
                "y": bounds.y(),
                "width": bounds.width(),
                "height": bounds.height(),
            },
            "color": color_hex,
        })
    return {"annotations": out, "total": len(out)}


def delete_annotation(window, params: dict) -> dict:
    """주석 삭제.

    파라미터:
    - `index` (int, required): 삭제할 주석 인덱스 (list_annotations 결과 기준).

    응답: success, error.
    """
    from image_editor.layers.annotation_layer import AnnotationLayer
    from image_editor.commands import RemoveAnnotationCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        index = int(params.get("index"))
    except (TypeError, ValueError):
        return {"success": False, "error": "index 정수 필요"}

    ann_layer = None
    for layer in tab.stack.layers:
        if isinstance(layer, AnnotationLayer):
            ann_layer = layer
            break
    if ann_layer is None:
        return {"success": False, "error": "주석 레이어 없음"}

    items = ann_layer.scene.annotations()
    if index < 0 or index >= len(items):
        return {"success": False, "error": f"잘못된 인덱스: {index} (범위: 0~{len(items)-1})"}

    item = items[index]
    cmd = RemoveAnnotationCommand(ann_layer.scene, item)
    tab.undo_stack.push(cmd)

    return {"success": True, "error": None}


def undo(window, params: dict) -> dict:
    """현재 이미지 탭에서 실행 취소.

    응답: success, can_undo (취소 후 추가 취소 가능 여부), error.
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "can_undo": False, "error": "활성 이미지 탭 없음"}
    if not tab.undo_stack.canUndo():
        return {"success": False, "can_undo": False, "error": "취소할 작업 없음"}
    tab.undo_stack.undo()
    return {"success": True, "can_undo": tab.undo_stack.canUndo(), "error": None}


def redo(window, params: dict) -> dict:
    """현재 이미지 탭에서 다시 실행.

    응답: success, can_redo (다시 실행 후 추가 다시 실행 가능 여부), error.
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "can_redo": False, "error": "활성 이미지 탭 없음"}
    if not tab.undo_stack.canRedo():
        return {"success": False, "can_redo": False, "error": "다시 실행할 작업 없음"}
    tab.undo_stack.redo()
    return {"success": True, "can_redo": tab.undo_stack.canRedo(), "error": None}


def get_tool_state(window, params: dict) -> dict:
    """현재 선택된 도구와 설정 조회.

    응답: tool_id, color(hex), thickness, brush_size, can_undo, can_redo.
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {
            "tool_id": None,
            "color": None,
            "thickness": None,
            "brush_size": None,
            "can_undo": False,
            "can_redo": False,
        }

    tool_id = window.tool_palette.current_tool() if hasattr(window, "tool_palette") else None
    color = window.annotation_toolbar.current_color().name() if hasattr(window, "annotation_toolbar") else None
    thickness = window.annotation_toolbar.current_thickness_step() if hasattr(window, "annotation_toolbar") else None
    brush_size = getattr(window, "_raster_brush_size", 20)

    return {
        "tool_id": tool_id,
        "color": color,
        "thickness": thickness,
        "brush_size": brush_size,
        "can_undo": tab.undo_stack.canUndo(),
        "can_redo": tab.undo_stack.canRedo(),
    }


# ===================== 선택/자르기 도구 =====================


def select_rect(window, params: dict) -> dict:
    """사각형 영역 선택 (marching ants).

    파라미터:
    - `x1`, `y1`, `x2`, `y2` (number, required): 선택 영역 좌표.

    응답: success, selection(x, y, width, height), error.
    """
    from PySide6.QtCore import QRect

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        x1 = int(params.get("x1"))
        y1 = int(params.get("y1"))
        x2 = int(params.get("x2"))
        y2 = int(params.get("y2"))
    except (TypeError, ValueError):
        return {"success": False, "error": "x1, y1, x2, y2 좌표 필요"}

    rect = QRect(x1, y1, x2 - x1, y2 - y1).normalized()
    if rect.width() <= 0 or rect.height() <= 0:
        return {"success": False, "error": "유효한 영역이 아님 (크기 0)"}

    tab.selection.set_rect(rect)
    return {
        "success": True,
        "selection": {
            "x": rect.x(), "y": rect.y(),
            "width": rect.width(), "height": rect.height(),
        },
        "error": None,
    }


def clear_selection(window, params: dict) -> dict:
    """선택 영역 해제.

    응답: success, error.
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    tab.selection.clear()
    return {"success": True, "error": None}


def get_selection(window, params: dict) -> dict:
    """현재 선택 영역 조회.

    응답: has_selection(bool), selection(x, y, width, height) or null.
    """
    tab = window._current_screenshot_tab()
    if tab is None:
        return {"has_selection": False, "selection": None}

    rect = tab.selection.rect()
    if rect is None or rect.width() <= 0 or rect.height() <= 0:
        return {"has_selection": False, "selection": None}

    return {
        "has_selection": True,
        "selection": {
            "x": rect.x(), "y": rect.y(),
            "width": rect.width(), "height": rect.height(),
        },
    }


def crop_image(window, params: dict) -> dict:
    """이미지 자르기. 선택 영역이 있으면 그 영역으로, 없으면 파라미터 좌표로 자름.

    파라미터:
    - `x1`, `y1`, `x2`, `y2` (number, optional): 자를 영역. 생략 시 현재 선택 영역 사용.

    응답: success, new_size(width, height), error.
    """
    from PySide6.QtCore import QRect
    from image_editor.operations.crop import CropCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    # 좌표 파라미터가 있으면 사용, 없으면 선택 영역 사용
    if params.get("x1") is not None:
        try:
            x1 = int(params.get("x1"))
            y1 = int(params.get("y1"))
            x2 = int(params.get("x2"))
            y2 = int(params.get("y2"))
        except (TypeError, ValueError):
            return {"success": False, "error": "좌표가 유효하지 않음"}
        rect = QRect(x1, y1, x2 - x1, y2 - y1).normalized()
    else:
        rect = tab.selection.rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return {"success": False, "error": "선택 영역 없음 (좌표 파라미터 필요)"}

    if rect.width() <= 0 or rect.height() <= 0:
        return {"success": False, "error": "자르기 영역 크기가 0"}

    # 캔버스 범위 체크
    canvas = tab.stack.canvas_size
    rect = rect.intersected(QRect(0, 0, canvas.width(), canvas.height()))
    if rect.width() <= 0 or rect.height() <= 0:
        return {"success": False, "error": "자르기 영역이 캔버스 밖"}

    cmd = CropCommand(tab.stack, rect)
    tab.undo_stack.push(cmd)
    tab.selection.clear()

    return {
        "success": True,
        "new_size": {"width": rect.width(), "height": rect.height()},
        "error": None,
    }


# ===================== 브러시/마스크 도구 =====================


def paint_stroke(window, params: dict) -> dict:
    """이미지 레이어에 브러시 스트로크 적용.

    파라미터:
    - `points` (list, required): 포인트 배열 [[x1, y1], [x2, y2], ...]. 최소 2개.
    - `color` (str, optional): hex 색상. 기본 검정 #000000.
    - `size` (int, optional): 브러시 크기 (픽셀). 기본 20.
    - `mode` (str, optional): "paint" 또는 "erase". 기본 "paint".

    응답: success, error.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.raster_paint import RasterPaintCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    points = params.get("points") or []
    if len(points) < 2:
        return {"success": False, "error": "최소 2개 포인트 필요"}

    color = _parse_color(params.get("color")) or QColor(0, 0, 0)
    size = int(params.get("size") or 20)
    size = max(1, min(200, size))
    mode = params.get("mode") or "paint"
    if mode not in ("paint", "erase"):
        return {"success": False, "error": "mode는 'paint' 또는 'erase'"}

    # 활성 이미지 레이어 확보
    window._ensure_active_image_layer(tab)
    layer = tab.stack.active_layer()
    if not isinstance(layer, ImageLayer):
        return {"success": False, "error": "이미지 레이어가 없음"}

    prev_pixmap = layer.pixmap.copy()
    offs = layer.offset

    # QPainter로 스트로크 그리기
    painter = QPainter(layer.pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if mode == "erase":
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        pen_color = QColor(0, 0, 0, 0)
    else:
        pen_color = color
    pen = QPen(pen_color)
    pen.setWidth(size)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    # 포인트 연결
    for i in range(len(points) - 1):
        try:
            x1, y1 = float(points[i][0]), float(points[i][1])
            x2, y2 = float(points[i+1][0]), float(points[i+1][1])
        except (TypeError, ValueError, IndexError):
            continue
        p1 = QPointF(x1 - offs.x(), y1 - offs.y())
        p2 = QPointF(x2 - offs.x(), y2 - offs.y())
        painter.drawLine(p1, p2)
    painter.end()

    # Undo 명령 등록
    new_pixmap = layer.pixmap.copy()
    cmd = RasterPaintCommand(tab.stack, layer.id, prev_pixmap, new_pixmap, "MCP 브러시")
    tab.undo_stack.push(cmd)
    tab.stack.notify_pixmap_changed(layer.id)

    return {"success": True, "error": None}


def paint_mask(window, params: dict) -> dict:
    """이미지 레이어의 마스크에 브러시 스트로크 적용.

    파라미터:
    - `points` (list, required): 포인트 배열 [[x1, y1], [x2, y2], ...]. 최소 2개.
    - `size` (int, optional): 브러시 크기 (픽셀). 기본 30.
    - `mode` (str, optional): "add" (불투명) 또는 "erase" (투명). 기본 "erase".

    응답: success, error.
    """
    from PySide6.QtCore import QPointF, QSize, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.mask_paint import MaskPaintCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    points = params.get("points") or []
    if len(points) < 2:
        return {"success": False, "error": "최소 2개 포인트 필요"}

    size = int(params.get("size") or 30)
    size = max(1, min(200, size))
    mode = params.get("mode") or "erase"
    if mode not in ("add", "erase"):
        return {"success": False, "error": "mode는 'add' 또는 'erase'"}

    # 활성 이미지 레이어 확보
    window._ensure_active_image_layer(tab)
    layer = tab.stack.active_layer()
    if not isinstance(layer, ImageLayer):
        return {"success": False, "error": "이미지 레이어가 없음"}

    # 마스크 준비 (없으면 생성)
    pm_size = QSize(layer.pixmap.width(), layer.pixmap.height())
    if layer.mask is None or layer.mask.isNull():
        mask = QImage(pm_size, QImage.Format_Grayscale8)
        mask.fill(255)  # 전체 불투명
        layer.mask = mask
    prev_mask = layer.mask.copy()

    offs = layer.offset

    # QPainter로 마스크에 그리기
    painter = QPainter(layer.mask)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if mode == "erase":
        pen_color = QColor(0, 0, 0)  # 투명으로
    else:
        pen_color = QColor(255, 255, 255)  # 불투명으로
    pen = QPen(pen_color)
    pen.setWidth(size)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    for i in range(len(points) - 1):
        try:
            x1, y1 = float(points[i][0]), float(points[i][1])
            x2, y2 = float(points[i+1][0]), float(points[i+1][1])
        except (TypeError, ValueError, IndexError):
            continue
        p1 = QPointF(x1 - offs.x(), y1 - offs.y())
        p2 = QPointF(x2 - offs.x(), y2 - offs.y())
        painter.drawLine(p1, p2)
    painter.end()

    # Undo 명령 등록
    new_mask = layer.mask.copy()
    cmd = MaskPaintCommand(tab.stack, layer.id, prev_mask, new_mask)
    tab.undo_stack.push(cmd)
    tab.stack.layers_changed.emit()

    return {"success": True, "error": None}


def apply_magic_wand(window, params: dict) -> dict:
    """마술봉으로 클릭 위치의 유사 색 영역 배경 제거.

    파라미터:
    - `x`, `y` (number, required): 클릭 좌표.
    - `tolerance` (int, optional): 색상 허용 범위 (0~255). 기본 32.

    응답: success, affected_rect (영향 영역), error.
    """
    from PySide6.QtCore import QRect
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.magic_wand import MagicWandCommand

    tab = window._current_screenshot_tab()
    if tab is None:
        return {"success": False, "error": "활성 이미지 탭 없음"}

    try:
        x = int(params.get("x"))
        y = int(params.get("y"))
    except (TypeError, ValueError):
        return {"success": False, "error": "x, y 좌표 필요"}

    tolerance = int(params.get("tolerance") or 32)
    tolerance = max(0, min(255, tolerance))

    # 활성 이미지 레이어 확보
    window._ensure_active_image_layer(tab)
    layer = tab.stack.active_layer()
    if not isinstance(layer, ImageLayer):
        return {"success": False, "error": "이미지 레이어가 없음"}

    # layer-local 좌표로 변환
    local_x = x - layer.offset.x()
    local_y = y - layer.offset.y()

    cmd = MagicWandCommand(tab.stack, layer.id, local_x, local_y, tolerance)
    tab.undo_stack.push(cmd)

    # 영향 영역 반환 (marching ants용)
    affected = cmd.affected_layer_rect()
    if affected is not None:
        # scene 좌표로 변환
        scene_rect = QRect(
            affected.x() + layer.offset.x(),
            affected.y() + layer.offset.y(),
            affected.width(),
            affected.height(),
        )
        tab.selection.set_rect(scene_rect)
        return {
            "success": True,
            "affected_rect": {
                "x": scene_rect.x(), "y": scene_rect.y(),
                "width": scene_rect.width(), "height": scene_rect.height(),
            },
            "error": None,
        }
    return {"success": True, "affected_rect": None, "error": None}


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
    # 그리기 도구
    "draw_rect": draw_rect,
    "draw_arrow": draw_arrow,
    "add_text": add_text,
    "list_annotations": list_annotations,
    "delete_annotation": delete_annotation,
    "undo": undo,
    "redo": redo,
    "get_tool_state": get_tool_state,
    # 선택/자르기 도구
    "select_rect": select_rect,
    "clear_selection": clear_selection,
    "get_selection": get_selection,
    "crop_image": crop_image,
    # 브러시/마스크 도구
    "paint_stroke": paint_stroke,
    "paint_mask": paint_mask,
    "apply_magic_wand": apply_magic_wand,
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
        # 그리기 도구
        {
            "name": "draw_rect",
            "description": "현재 이미지 탭에 사각형 주석 추가.",
            "params": {
                "x1": {"type": "number", "required": True, "description": "좌상단 x"},
                "y1": {"type": "number", "required": True, "description": "좌상단 y"},
                "x2": {"type": "number", "required": True, "description": "우하단 x"},
                "y2": {"type": "number", "required": True, "description": "우하단 y"},
                "color": {"type": "string", "required": False, "description": "hex 색상 (#RRGGBB). 기본 빨강"},
                "thickness": {"type": "integer", "required": False, "description": "두께 step (0~4). 기본 1"},
            },
        },
        {
            "name": "draw_arrow",
            "description": "현재 이미지 탭에 화살표 주석 추가.",
            "params": {
                "x1": {"type": "number", "required": True, "description": "시작점 x"},
                "y1": {"type": "number", "required": True, "description": "시작점 y"},
                "x2": {"type": "number", "required": True, "description": "끝점 x (화살표 머리)"},
                "y2": {"type": "number", "required": True, "description": "끝점 y (화살표 머리)"},
                "color": {"type": "string", "required": False, "description": "hex 색상. 기본 빨강"},
                "thickness": {"type": "integer", "required": False, "description": "두께 step (0~4). 기본 1"},
            },
        },
        {
            "name": "add_text",
            "description": "현재 이미지 탭에 텍스트 주석 추가.",
            "params": {
                "x": {"type": "number", "required": True, "description": "텍스트 x 좌표"},
                "y": {"type": "number", "required": True, "description": "텍스트 y 좌표"},
                "text": {"type": "string", "required": True, "description": "표시할 텍스트"},
                "color": {"type": "string", "required": False, "description": "hex 색상. 기본 빨강"},
            },
        },
        {
            "name": "list_annotations",
            "description": "현재 이미지 탭의 주석 목록 조회.",
            "params": {},
        },
        {
            "name": "delete_annotation",
            "description": "주석 삭제.",
            "params": {
                "index": {"type": "integer", "required": True, "description": "삭제할 주석 인덱스"},
            },
        },
        {
            "name": "undo",
            "description": "현재 이미지 탭에서 실행 취소.",
            "params": {},
        },
        {
            "name": "redo",
            "description": "현재 이미지 탭에서 다시 실행.",
            "params": {},
        },
        {
            "name": "get_tool_state",
            "description": "현재 선택된 도구와 설정 조회.",
            "params": {},
        },
        # 선택/자르기 도구
        {
            "name": "select_rect",
            "description": "사각형 영역 선택 (marching ants).",
            "params": {
                "x1": {"type": "number", "required": True, "description": "좌상단 x"},
                "y1": {"type": "number", "required": True, "description": "좌상단 y"},
                "x2": {"type": "number", "required": True, "description": "우하단 x"},
                "y2": {"type": "number", "required": True, "description": "우하단 y"},
            },
        },
        {
            "name": "clear_selection",
            "description": "선택 영역 해제.",
            "params": {},
        },
        {
            "name": "get_selection",
            "description": "현재 선택 영역 조회.",
            "params": {},
        },
        {
            "name": "crop_image",
            "description": "이미지 자르기. 좌표 생략 시 현재 선택 영역 사용.",
            "params": {
                "x1": {"type": "number", "required": False, "description": "좌상단 x"},
                "y1": {"type": "number", "required": False, "description": "좌상단 y"},
                "x2": {"type": "number", "required": False, "description": "우하단 x"},
                "y2": {"type": "number", "required": False, "description": "우하단 y"},
            },
        },
        # 브러시/마스크 도구
        {
            "name": "paint_stroke",
            "description": "이미지 레이어에 브러시 스트로크 적용.",
            "params": {
                "points": {"type": "array", "required": True, "description": "[[x1,y1],[x2,y2],...] 최소 2개"},
                "color": {"type": "string", "required": False, "description": "hex 색상. 기본 검정"},
                "size": {"type": "integer", "required": False, "description": "브러시 크기 (1~200). 기본 20"},
                "mode": {"type": "string", "required": False, "description": "'paint' 또는 'erase'. 기본 paint"},
            },
        },
        {
            "name": "paint_mask",
            "description": "이미지 레이어의 마스크에 브러시 스트로크 적용.",
            "params": {
                "points": {"type": "array", "required": True, "description": "[[x1,y1],[x2,y2],...] 최소 2개"},
                "size": {"type": "integer", "required": False, "description": "브러시 크기 (1~200). 기본 30"},
                "mode": {"type": "string", "required": False, "description": "'add'(불투명) 또는 'erase'(투명). 기본 erase"},
            },
        },
        {
            "name": "apply_magic_wand",
            "description": "마술봉으로 클릭 위치의 유사 색 영역 배경 제거.",
            "params": {
                "x": {"type": "number", "required": True, "description": "클릭 x 좌표"},
                "y": {"type": "number", "required": True, "description": "클릭 y 좌표"},
                "tolerance": {"type": "integer", "required": False, "description": "색상 허용 범위 (0~255). 기본 32"},
            },
        },
    ]
