"""backends/factory.py 단위 테스트 — 7 케이스.

factory 가 ModelMetadata.runtime 에 따라 올바른 ChatBackend 인스턴스를 돌려주고,
tools dict 형식이 backend 별로 맞는지, dependency label 이 정확한지 검증.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def claude_meta():
    """claude-sonnet-4-6 ModelMetadata mock."""
    m = MagicMock()
    m.id = "claude-sonnet-4-6"
    m.runtime = "claude"
    m.repo_id = None
    m.modalities = frozenset({"text"})
    m.quantization = None
    m.tool_strategy = "mcp"
    return m


@pytest.fixture
def transformers_meta():
    """qwen25-7b-instruct ModelMetadata mock (bf16, text only)."""
    m = MagicMock()
    m.id = "qwen25-7b-instruct"
    m.runtime = "transformers"
    m.repo_id = "Qwen/Qwen2.5-7B-Instruct"
    m.modalities = frozenset({"text"})
    m.quantization = "bf16 (원본)"
    m.tool_strategy = "official"
    return m


@pytest.fixture
def ollama_meta():
    """qwen3-8b-ollama ModelMetadata mock."""
    m = MagicMock()
    m.id = "qwen3-8b-ollama"
    m.runtime = "ollama"
    m.repo_id = "qwen3:8b"
    m.modalities = frozenset({"text"})
    m.quantization = None
    m.tool_strategy = "official"
    return m


@pytest.fixture
def video_tools_mock():
    """VideoTools mock — mcp + openai tools 양쪽 제공."""
    vt = MagicMock()
    vt.mcp_server.return_value = MagicMock()
    vt.tool_names.return_value = ["mcp__kstudio_video__get_video_state"]
    vt.openai_tools_and_handlers.return_value = (
        [{"type": "function", "function": {"name": "get_video_state",
                                           "description": "x", "parameters": {}}}],
        {"get_video_state": lambda a: {"ok": True}},
    )
    return vt


# ---------------------------------------------------------------------------
# 테스트 1: claude backend 정상 생성
# ---------------------------------------------------------------------------

def test_create_backend_claude(claude_meta, tmp_path, monkeypatch):
    """create_backend 가 claude runtime 에 ClaudeBackend 반환."""
    import screen_recorder.agent.backends.factory as factory_mod
    from screen_recorder.agent.backends.claude_backend import ClaudeBackend

    captured = {}

    class _SpyClaude(ClaudeBackend):
        def __init__(self, cwd):
            captured["cwd"] = cwd
            super().__init__(cwd=cwd)

    monkeypatch.setattr(factory_mod, "ClaudeBackend", _SpyClaude)

    from screen_recorder.agent.backends.factory import create_backend
    backend = create_backend(claude_meta, cwd=tmp_path)

    assert isinstance(backend, ClaudeBackend)
    assert captured["cwd"] == tmp_path


# ---------------------------------------------------------------------------
# 테스트 2: transformers backend 정상 생성 (Omni bf16 → load_in_4bit=False)
# ---------------------------------------------------------------------------

def test_create_backend_transformers_bf16(transformers_meta, tmp_path, monkeypatch):
    """transformers backend, quantization='bf16 (원본)' → load_in_4bit=False."""
    import screen_recorder.agent.backends.factory as factory_mod
    from screen_recorder.agent.backends.transformers_backend import TransformersBackend

    captured = {}

    class _SpyTransformers(TransformersBackend):
        def __init__(self, repo_id, modalities=None, load_in_4bit=False):
            captured["repo_id"] = repo_id
            captured["modalities"] = modalities
            captured["load_in_4bit"] = load_in_4bit
            super().__init__(repo_id, modalities, load_in_4bit=load_in_4bit)

    monkeypatch.setattr(factory_mod, "TransformersBackend", _SpyTransformers)

    from screen_recorder.agent.backends.factory import create_backend
    backend = create_backend(transformers_meta, cwd=tmp_path)

    assert isinstance(backend, TransformersBackend)
    assert captured["repo_id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert captured["load_in_4bit"] is False  # "4-bit" not in "bf16 (원본)"


# ---------------------------------------------------------------------------
# 테스트 3: ollama backend 정상 생성
# ---------------------------------------------------------------------------

def test_create_backend_ollama(ollama_meta, tmp_path, monkeypatch):
    """ollama backend → OllamaBackend(model_tag='qwen3:8b')."""
    import screen_recorder.agent.backends.factory as factory_mod
    from screen_recorder.agent.backends.ollama_backend import OllamaBackend

    captured = {}

    class _SpyOllama(OllamaBackend):
        def __init__(self, model_tag, base_url="http://localhost:11434", think=False):
            captured["model_tag"] = model_tag
            super().__init__(model_tag, base_url=base_url, think=think)

    monkeypatch.setattr(factory_mod, "OllamaBackend", _SpyOllama)

    from screen_recorder.agent.backends.factory import create_backend
    backend = create_backend(ollama_meta, cwd=tmp_path)

    assert isinstance(backend, OllamaBackend)
    assert captured["model_tag"] == "qwen3:8b"


# ---------------------------------------------------------------------------
# 테스트 4: 미지원 runtime → NotImplementedError
# ---------------------------------------------------------------------------

def test_create_backend_unknown_runtime_raises(tmp_path):
    """알 수 없는 runtime 값 → NotImplementedError."""
    from screen_recorder.agent.backends.factory import create_backend

    meta = MagicMock()
    meta.id = "some-llm"
    meta.runtime = "llama-cpp-future"  # 미지원
    meta.repo_id = "some/model"
    meta.quantization = None

    with pytest.raises(NotImplementedError, match="llama-cpp-future"):
        create_backend(meta, cwd=tmp_path)


# ---------------------------------------------------------------------------
# 테스트 5: claude tools dict shape 검증
# ---------------------------------------------------------------------------

def test_build_backend_tools_claude(claude_meta, video_tools_mock):
    """claude runtime → {"mcp_server", "allowed_tools"} shape."""
    from screen_recorder.agent.backends.factory import build_backend_tools

    td = build_backend_tools(claude_meta, video_tools_mock)

    assert "mcp_server" in td
    assert "allowed_tools" in td
    assert "openai_tools" not in td


# ---------------------------------------------------------------------------
# 테스트 6: transformers tools dict shape 검증
# ---------------------------------------------------------------------------

def test_build_backend_tools_transformers(transformers_meta, video_tools_mock):
    """transformers runtime → {"openai_tools", "tool_handlers", "tool_strategy"} shape."""
    from screen_recorder.agent.backends.factory import build_backend_tools

    td = build_backend_tools(transformers_meta, video_tools_mock)

    assert "openai_tools" in td
    assert "tool_handlers" in td
    assert td["tool_strategy"] == "official"
    assert "mcp_server" not in td


# ---------------------------------------------------------------------------
# 테스트 7: runtime_dependency_label — 알려진/모르는 runtime
# ---------------------------------------------------------------------------

def test_runtime_dependency_label_known_and_unknown():
    """알려진 runtime 은 사람이 읽을 수 있는 레이블, 모르는 건 runtime 값 그대로."""
    from screen_recorder.agent.backends.factory import runtime_dependency_label

    assert "transformers" in runtime_dependency_label("transformers").lower()
    assert "llama" in runtime_dependency_label("llama-cpp").lower()
    assert "ollama" in runtime_dependency_label("ollama").lower()
    # 미지원 runtime 은 그대로 반환
    assert runtime_dependency_label("unknown-runtime-xyz") == "unknown-runtime-xyz"
