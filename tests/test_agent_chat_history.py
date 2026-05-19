"""ChatPanel 대화 기록 영속화."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from screen_recorder.agent.chat_history import (
    HISTORY_SCHEMA_VERSION, MAX_MESSAGES, PERSISTABLE_ROLES,
    load_history, save_history,
)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "ch.json"
    messages = [
        ("user", "안녕"),
        ("assistant", "안녕하세요!"),
        ("tool_use", "🔧 get_sidecar_summary()"),
        ("tool_result", "← 효과 없음"),
    ]
    save_history(path, messages)
    loaded = load_history(path)
    assert loaded == messages


def test_save_truncates_to_max(tmp_path: Path) -> None:
    path = tmp_path / "ch.json"
    many = [("user", f"msg {i}") for i in range(MAX_MESSAGES + 50)]
    save_history(path, many)
    loaded = load_history(path)
    assert len(loaded) == MAX_MESSAGES
    # 끝 부분 (최신) 이 보존.
    assert loaded[-1][1] == f"msg {MAX_MESSAGES + 49}"


def test_load_missing(tmp_path: Path) -> None:
    assert load_history(tmp_path / "no.json") == []


def test_load_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not valid json", encoding="utf-8")
    assert load_history(path) == []


def test_load_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"version": 999, "messages": []}), encoding="utf-8")
    assert load_history(path) == []


def test_load_filters_unknown_roles(tmp_path: Path) -> None:
    """저장 시 다른 role 이 들어가도 load 시 PERSISTABLE_ROLES 만 통과."""
    path = tmp_path / "mix.json"
    data = {
        "version": HISTORY_SCHEMA_VERSION,
        "messages": [
            {"role": "user", "text": "ok"},
            {"role": "thinking", "text": "should skip"},   # PERSISTABLE_ROLES 외.
            {"role": "assistant", "text": "ok2"},
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_history(path)
    assert ("user", "ok") in loaded
    assert ("assistant", "ok2") in loaded
    assert all(r != "thinking" for r, _ in loaded)


def test_persistable_roles_includes_essentials() -> None:
    """주요 role 들이 모두 영속화 대상."""
    for role in ("user", "assistant", "tool_use", "tool_result", "system", "error"):
        assert role in PERSISTABLE_ROLES
