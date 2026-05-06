"""KStudio stdio MCP 서버 — LLM CLI 가 spawn 하는 자식 프로세스.

CLI(Claude Code / Gemini CLI / Codex 등) 가 이 스크립트를 stdio MCP 서버로 등록.
스크립트는 KStudio HTTP 브리지(`127.0.0.1:<port>`) 를 호출해 도구를 노출한다.

연결 정보(포트/토큰) 는 두 가지 경로로 받는다:
1. 환경변수 `KSTUDIO_MCP_PORT`, `KSTUDIO_MCP_TOKEN` 우선
2. 없으면 `~/AppData/Local/KStudio/settings.json` 의 mcp 섹션 (시스템 단일 설치 가정)

KStudio 가 안 떠있으면 도구 호출이 실패. 사용자 친화 메시지로 "KStudio 를 먼저
실행하세요" 안내.

실행: `python -m screen_recorder.mcp.stdio_server`
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:   # pragma: no cover — 의존성 없는 환경 안내
    print(
        "ERROR: mcp 패키지가 설치돼있지 않습니다. `pip install mcp` 후 다시 시도하세요.",
        file=sys.stderr,
    )
    raise


# ---------- 연결 정보 ----------

def _settings_path() -> Path:
    return Path.home() / "AppData" / "Local" / "KStudio" / "settings.json"


def _load_connection() -> tuple[int, str]:
    """포트 + 토큰을 환경변수 → settings.json 순으로 조회."""
    port_env = os.environ.get("KSTUDIO_MCP_PORT")
    token_env = os.environ.get("KSTUDIO_MCP_TOKEN")
    if port_env and token_env:
        return int(port_env), token_env
    p = _settings_path()
    if not p.exists():
        raise RuntimeError(
            "KStudio settings.json 을 찾을 수 없습니다. KStudio 를 한 번 실행해 "
            "MCP 를 활성화한 뒤 다시 시도하세요."
        )
    raw = json.loads(p.read_text(encoding="utf-8"))
    mcp_cfg = raw.get("mcp", {})
    if not mcp_cfg.get("enabled"):
        raise RuntimeError(
            "KStudio MCP 가 꺼져있습니다. 환경설정 → MCP 에서 활성화하세요."
        )
    port = int(mcp_cfg.get("port") or 0)
    token = mcp_cfg.get("token") or ""
    if not port or not token:
        raise RuntimeError(
            "KStudio MCP 설정이 비어있습니다. 환경설정에서 다시 활성화 후 KStudio 를 "
            "재시작하세요."
        )
    return port, token


# ---------- HTTP 호출 헬퍼 ----------

def _http_call(tool_name: str, params: dict) -> dict:
    """KStudio HTTP 브리지로 도구 호출. 응답 result dict 반환."""
    port, token = _load_connection()
    url = f"http://127.0.0.1:{port}/mcp/v1/call/{tool_name}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, headers=headers, json=params)
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"KStudio 가 실행 중이 아닙니다 (127.0.0.1:{port} 연결 실패). "
            f"KStudio 를 먼저 실행하세요. 원본 에러: {e}"
        )
    if r.status_code == 401:
        raise RuntimeError(
            "KStudio MCP 토큰 불일치 — 환경설정에서 MCP 를 비활성→활성으로 토글한 "
            "뒤 CLI 를 재등록하세요."
        )
    if r.status_code >= 400:
        try:
            err = r.json().get("error", r.text)
        except Exception:   # noqa: BLE001
            err = r.text
        raise RuntimeError(f"도구 호출 실패 ({r.status_code}): {err}")
    return r.json().get("result", {})


# ---------- MCP 서버 정의 ----------

mcp = FastMCP("kstudio")


@mcp.tool()
def get_current_image_path() -> dict:
    """현재 KStudio 에서 활성 상태인 이미지 탭의 디스크 경로와 메타데이터를 가져온다.

    탭이 없으면 has_tab=False 반환. 캡처 직후 미저장이면 path=null.
    """
    return _http_call("get_current_image_path", {})


@mcp.tool()
def list_library(kind: Optional[str] = None) -> dict:
    """현재 세션의 KStudio 라이브러리(스크린샷·녹화 영상) 목록을 조회.

    Args:
        kind: "image" 또는 "video" 로 필터. 생략하면 전체.
    """
    return _http_call("list_library", {"kind": kind} if kind else {})


@mcp.tool()
def list_tabs() -> dict:
    """현재 KStudio 에 열려있는 탭 목록과 활성 탭 인덱스를 조회."""
    return _http_call("list_tabs", {})


@mcp.tool()
def get_current_mode() -> dict:
    """KStudio 의 현재 모드 — "image" 또는 "video"."""
    return _http_call("get_current_mode", {})


@mcp.tool()
def get_save_dirs() -> dict:
    """KStudio 의 이미지/영상 저장 폴더 절대 경로와 파일명 패턴."""
    return _http_call("get_save_dirs", {})


@mcp.tool()
def get_settings_summary() -> dict:
    """KStudio 의 핵심 설정 스냅샷 (저장 폴더, 코덱, 모드 등). 토큰 등 민감정보는 제외."""
    return _http_call("get_settings_summary", {})


# ---------- 명령 도구 (sync) ----------


@mcp.tool()
def open_image_path(path: str) -> dict:
    """디스크의 이미지 파일을 KStudio 새 탭으로 연다.

    Args:
        path: 절대 경로. 지원 확장자 — png, jpg, jpeg, webp, bmp, kstudio.
    """
    return _http_call("open_image_path", {"path": path})


@mcp.tool()
def save_current_tab() -> dict:
    """현재 활성 이미지 탭을 디스크에 저장한다."""
    return _http_call("save_current_tab", {})


@mcp.tool()
def set_mode(mode: str) -> dict:
    """KStudio 의 모드 전환.

    Args:
        mode: "image" 또는 "video".
    """
    return _http_call("set_mode", {"mode": mode})


@mcp.tool()
def resize_image(target_w: int, target_h: int) -> dict:
    """현재 이미지 탭을 LANCZOS 로 리사이즈해 새 PNG 파일 생성. 원본 보존.

    더 고품질의 AI 업스케일은 `ai_upscale` 도구를 사용.

    Args:
        target_w: 목표 가로 픽셀 (1~16384).
        target_h: 목표 세로 픽셀 (1~16384).
    """
    return _http_call("resize_image", {"target_w": target_w, "target_h": target_h})


# ---------- 명령 도구 (async via request_id) ----------


@mcp.tool()
def ai_upscale(target_w: int, target_h: int) -> dict:
    """Real-ESRGAN x4 AI 업스케일. 비동기 — request_id 반환.

    수십 초 ~ 수 분 걸릴 수 있어 즉시 request_id 반환. 결과는 `get_request_status`
    로 폴링한다 (status: "pending" → "done" / "failed").

    Args:
        target_w: 목표 가로 픽셀 (원본보다 커야 함).
        target_h: 목표 세로 픽셀 (원본보다 커야 함).
    """
    return _http_call("ai_upscale", {"target_w": target_w, "target_h": target_h})


@mcp.tool()
def remove_background(model: Optional[str] = None) -> dict:
    """현재 이미지 레이어의 배경을 자동 제거 (rembg). 비동기 — request_id 반환.

    Args:
        model: rembg 모델 id. 생략하면 사용자 설정 기본값(보통 "u2net").
            선택지: u2net / isnet-general-use / u2netp / silueta / u2net_human_seg /
            isnet-anime / birefnet-general / birefnet-general-lite / birefnet-portrait.
    """
    params = {"model": model} if model else {}
    return _http_call("remove_background", params)


@mcp.tool()
def get_request_status(request_id: str) -> dict:
    """비동기 도구가 발급한 request_id 의 현재 상태/결과를 조회한다.

    응답 status 가 "done" 이면 result 필드에 결과 dict 가 담긴다. "failed" 면 error 필드.
    """
    return _http_call("get_request_status", {"request_id": request_id})


def main() -> None:
    """`python -m screen_recorder.mcp.stdio_server` 진입점."""
    mcp.run()


if __name__ == "__main__":   # pragma: no cover
    main()
