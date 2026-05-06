"""KStudio MCP 를 LLM CLI 에 자동 등록 — Claude Code / Gemini CLI / Codex.

각 CLI 의 설정 파일을 직접 편집해 KStudio stdio MCP 서버를 등록한다. stdio
서버(`stdio_server.py`) 는 settings.json 에서 토큰/포트를 자동 로드하므로 등록 시
env 변수를 넘길 필요는 없지만, 명시성과 단일 PC 다중 사용자 케이스를 대비해
함께 넘긴다.

각 함수는 (success: bool, message: str) 반환. 실패해도 다른 CLI 등록은 계속.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ---------- 공통 ----------

def _python_command() -> tuple[str, list[str]]:
    """현재 Python 인터프리터 + stdio 서버 모듈 호출.

    가상환경에서 실행 중이면 그 venv 의 python.exe 가 sys.executable.
    Frozen 빌드(PyInstaller) 는 별도 entry point 가 필요해 현재는 dev 모드 가정 —
    frozen 일 때는 호출자가 사전 검사하고 명시적 안내를 띄워야.
    """
    return sys.executable, ["-m", "screen_recorder.mcp.stdio_server"]


def _connection_env(port: int, token: str) -> dict:
    return {
        "KSTUDIO_MCP_PORT": str(port),
        "KSTUDIO_MCP_TOKEN": token,
    }


# ---------- Claude Code ----------

def register_for_claude_code(port: int, token: str) -> tuple[bool, str]:
    """`claude mcp add` 명령으로 KStudio 등록. claude CLI 가 PATH 에 있어야.

    user 스코프(전역) 에 등록 — 어느 폴더에서 claude 를 실행해도 KStudio 도구 사용 가능.
    이미 등록돼 있으면 한 번 제거 후 재등록 (idempotent).
    """
    claude = shutil.which("claude")
    if claude is None:
        return (False, "Claude Code CLI 가 PATH 에 없음. https://claude.com/claude-code 에서 설치.")

    cmd_python, cmd_args = _python_command()
    env = _connection_env(port, token)

    # 기존 등록 제거 — 실패해도 무시 (없을 수도 있으니).
    try:
        subprocess.run(
            [claude, "mcp", "remove", "kstudio", "-s", "user"],
            check=False, capture_output=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        pass

    # 새로 등록 — `--` 뒤가 실제 명령. -e KEY=VALUE 로 env.
    args = [claude, "mcp", "add", "kstudio", "-s", "user"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += ["--", cmd_python, *cmd_args]
    try:
        result = subprocess.run(args, capture_output=True, timeout=15, text=True)
    except (subprocess.SubprocessError, OSError) as e:
        return (False, f"claude mcp add 실행 실패: {e}")
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip() or "알 수 없는 에러"
        return (False, f"claude mcp add 실패 (exit {result.returncode}): {msg}")
    return (True, "Claude Code 에 등록 완료 (user 스코프). 새 claude 세션부터 적용.")


# ---------- Gemini CLI ----------

def _gemini_settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def register_for_gemini(port: int, token: str) -> tuple[bool, str]:
    """`~/.gemini/settings.json` 의 `mcpServers` 에 KStudio 항목 추가.

    Gemini CLI 는 설정 파일 기반 — 명령 도구는 없으므로 직접 편집한다.
    파일이 없으면 새로 생성. 기존 mcpServers 는 보존, kstudio 키만 갱신.
    """
    cmd_python, cmd_args = _python_command()
    env = _connection_env(port, token)

    p = _gemini_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except json.JSONDecodeError:
            return (False, f"{p} 파싱 실패 — 수동 수정 필요.")
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return (False, "settings.json 의 mcpServers 가 dict 가 아님 — 수동 수정 필요.")
    servers["kstudio"] = {
        "command": cmd_python,
        "args": cmd_args,
        "env": env,
    }
    try:
        p.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        return (False, f"settings.json 쓰기 실패: {e}")
    return (True, f"Gemini CLI 에 등록 완료 ({p}). 새 gemini 세션부터 적용.")


# ---------- Codex CLI (best effort) ----------

def _codex_config_path() -> Optional[Path]:
    """Codex CLI 의 설정 파일 — 알려진 경로들 중 존재하는 첫 것.

    버전마다 위치가 다를 수 있고 MCP 클라이언트 지원이 부분적이라 추측한 후보들.
    """
    candidates = [
        Path.home() / ".codex" / "config.toml",
        Path.home() / ".codex" / "config.json",
        Path.home() / ".config" / "codex" / "config.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def register_for_codex(port: int, token: str) -> tuple[bool, str]:
    """Codex CLI 등록 시도 — best effort.

    OpenAI Codex CLI 의 MCP 클라이언트 지원이 버전마다 다르고, 공식 설정 스키마도
    유동적이라 자동 등록은 베타. 실패하면 사용자에게 수동 등록을 안내.
    """
    cmd_python, cmd_args = _python_command()
    env = _connection_env(port, token)

    cfg = _codex_config_path()
    cmd_str = f"{cmd_python} {' '.join(cmd_args)}"
    if cfg is None:
        return (False,
                "Codex CLI 설정 파일을 찾지 못함. 수동 등록:\n"
                f"  command: {cmd_python}\n  args: {' '.join(cmd_args)}\n"
                f"  env: KSTUDIO_MCP_PORT={port} KSTUDIO_MCP_TOKEN={token}")

    # JSON 만 자동 처리 (TOML 은 별도 파서 필요 — 일단 안내).
    if cfg.suffix == ".json":
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return (False, f"{cfg} 파싱 실패 — 수동 수정 필요.")
        servers = data.setdefault("mcpServers", {})
        servers["kstudio"] = {"command": cmd_python, "args": cmd_args, "env": env}
        try:
            cfg.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            return (False, f"설정 쓰기 실패: {e}")
        return (True, f"Codex 에 등록 시도 완료 ({cfg}). 동작 여부는 codex 버전에 따라 다름.")
    return (False,
            f"Codex 설정({cfg}) 형식이 TOML — 자동 편집 미지원. 수동 등록 필요:\n"
            f"  command: {cmd_python}\n  args: {' '.join(cmd_args)}\n"
            f"  env: KSTUDIO_MCP_PORT={port} KSTUDIO_MCP_TOKEN={token}")


# ---------- 일괄 등록 ----------

def register_all(port: int, token: str) -> dict[str, tuple[bool, str]]:
    """3종 CLI 모두 시도. 결과 dict — 각 CLI 별 (success, message)."""
    return {
        "claude": register_for_claude_code(port, token),
        "gemini": register_for_gemini(port, token),
        "codex": register_for_codex(port, token),
    }
