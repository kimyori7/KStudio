"""CLI 등록 헬퍼 테스트 — 실제 CLI 가 없어도 설정 파일 편집은 검증 가능.

claude CLI 호출은 shutil.which 로 PATH 확인 후 subprocess — 둘 다 monkeypatch.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from screen_recorder.mcp import cli_register


def test_python_command_uses_sys_executable():
    cmd, args = cli_register._python_command()
    assert cmd  # 빈 문자열 X
    assert args[0] == "-m"
    assert args[1] == "screen_recorder.mcp.stdio_server"


def test_connection_env():
    env = cli_register._connection_env(1234, "abcd")
    assert env["KSTUDIO_MCP_PORT"] == "1234"
    assert env["KSTUDIO_MCP_TOKEN"] == "abcd"


# ---------- Claude Code ----------

def test_register_claude_no_cli(monkeypatch):
    """claude CLI 가 없으면 친화적 에러 반환, 예외 X."""
    monkeypatch.setattr(cli_register.shutil, "which", lambda _name: None)
    ok, msg = cli_register.register_for_claude_code(8000, "tok")
    assert ok is False
    assert "Claude Code CLI" in msg


def test_register_claude_invokes_subprocess(monkeypatch):
    """claude 가 있으면 add 명령이 호출되고 성공 응답."""
    monkeypatch.setattr(cli_register.shutil, "which", lambda _name: "C:/fake/claude.exe")
    calls = []

    class _R:
        def __init__(self, rc): self.returncode, self.stdout, self.stderr = rc, "", ""

    def fake_run(args, **kw):
        calls.append(args)
        return _R(0)

    monkeypatch.setattr(cli_register.subprocess, "run", fake_run)
    ok, _ = cli_register.register_for_claude_code(9000, "deadbeef")
    assert ok is True
    # remove + add 두 번 호출
    assert len(calls) == 2
    add_args = calls[1]
    assert "mcp" in add_args and "add" in add_args
    # env 옵션 (-e KEY=VALUE) 확인
    flat = " ".join(add_args)
    assert "KSTUDIO_MCP_PORT=9000" in flat
    assert "KSTUDIO_MCP_TOKEN=deadbeef" in flat


def test_register_claude_propagates_error(monkeypatch):
    monkeypatch.setattr(cli_register.shutil, "which", lambda _name: "C:/fake/claude.exe")
    monkeypatch.setattr(cli_register.subprocess, "run",
                        lambda *a, **kw: type("R", (), {
                            "returncode": 1, "stdout": "", "stderr": "boom",
                        })())
    ok, msg = cli_register.register_for_claude_code(1, "t")
    assert ok is False
    assert "boom" in msg


# ---------- Gemini CLI ----------

def test_register_gemini_creates_file(tmp_path, monkeypatch):
    settings = tmp_path / ".gemini" / "settings.json"
    monkeypatch.setattr(cli_register, "_gemini_settings_path", lambda: settings)
    ok, msg = cli_register.register_for_gemini(7777, "g_tok")
    assert ok is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    server = data["mcpServers"]["kstudio"]
    assert server["env"]["KSTUDIO_MCP_PORT"] == "7777"
    assert server["env"]["KSTUDIO_MCP_TOKEN"] == "g_tok"
    assert "screen_recorder.mcp.stdio_server" in " ".join(server["args"])


def test_register_gemini_preserves_existing_servers(tmp_path, monkeypatch):
    """다른 MCP 서버 설정은 보존, kstudio 만 갱신."""
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({
            "mcpServers": {
                "other": {"command": "x", "args": [], "env": {}},
                "kstudio": {"command": "old"},
            },
            "unrelated_field": "preserved",
        }), encoding="utf-8")
    monkeypatch.setattr(cli_register, "_gemini_settings_path", lambda: settings)
    cli_register.register_for_gemini(1234, "tok")
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"]["command"] == "x"
    assert data["mcpServers"]["kstudio"]["env"]["KSTUDIO_MCP_PORT"] == "1234"
    assert data["unrelated_field"] == "preserved"


def test_register_gemini_handles_corrupt_settings(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(cli_register, "_gemini_settings_path", lambda: settings)
    ok, msg = cli_register.register_for_gemini(1, "t")
    assert ok is False
    assert "파싱 실패" in msg


# ---------- Codex (best effort) ----------

def test_register_codex_no_config(monkeypatch):
    monkeypatch.setattr(cli_register, "_codex_config_path", lambda: None)
    ok, msg = cli_register.register_for_codex(1, "t")
    assert ok is False
    assert "수동 등록" in msg


def test_register_codex_writes_json(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_register, "_codex_config_path", lambda: cfg)
    ok, _ = cli_register.register_for_codex(5555, "ctok")
    assert ok is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["mcpServers"]["kstudio"]["env"]["KSTUDIO_MCP_PORT"] == "5555"


def test_register_codex_skips_toml(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("# placeholder", encoding="utf-8")
    monkeypatch.setattr(cli_register, "_codex_config_path", lambda: cfg)
    ok, msg = cli_register.register_for_codex(1, "t")
    assert ok is False
    assert "TOML" in msg


# ---------- 일괄 ----------

def test_register_all_returns_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(cli_register.shutil, "which", lambda _: None)
    monkeypatch.setattr(cli_register, "_gemini_settings_path",
                        lambda: tmp_path / "g.json")
    monkeypatch.setattr(cli_register, "_codex_config_path", lambda: None)
    res = cli_register.register_all(1000, "tok")
    assert set(res.keys()) == {"claude", "gemini", "codex"}
    # 각 항목은 (bool, str) 튜플
    for k, v in res.items():
        assert isinstance(v, tuple)
        assert isinstance(v[0], bool)
        assert isinstance(v[1], str)
    # gemini 는 성공 (파일 생성), claude/codex 는 실패 (CLI 없음)
    assert res["gemini"][0] is True
    assert res["claude"][0] is False
    assert res["codex"][0] is False
