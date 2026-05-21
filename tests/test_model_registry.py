"""ModelRegistry 단위 테스트 — built-in 4개 + dependency check."""
from __future__ import annotations

import pytest

from screen_recorder.agent.models import ModelMetadata, ModelRegistry


def test_builtin_models_count_and_ids():
    """built-in 5개: Claude opus/sonnet/haiku + Qwen2.5-7B-Instruct + Qwen2.5-Omni 7B."""
    reg = ModelRegistry()
    models = reg.all_models()
    ids = [m.id for m in models]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-6" in ids
    assert "claude-haiku-4-5-20251001" in ids
    assert "qwen25-7b-instruct" in ids
    assert "qwen25-omni-7b" in ids
    assert len(models) == 5


def test_get_returns_metadata_by_id():
    reg = ModelRegistry()
    qwen = reg.get("qwen25-omni-7b")
    assert qwen is not None
    assert qwen.runtime == "transformers"
    assert qwen.repo_id == "Qwen/Qwen2.5-Omni-7B"
    assert "image" in qwen.modalities


def test_get_returns_none_for_unknown_id():
    reg = ModelRegistry()
    assert reg.get("nonexistent-model") is None


def test_claude_metadata_has_no_repo_id():
    """Claude 는 클라우드 모델 — repo_id None."""
    reg = ModelRegistry()
    claude = reg.get("claude-sonnet-4-6")
    assert claude.runtime == "claude"
    assert claude.repo_id is None
    assert claude.estimated_size_gb == 0


def test_check_runtime_available_claude_always_true():
    """claude 런타임은 claude_agent_sdk 이미 설치됨 — 항상 True."""
    from screen_recorder.agent.models import check_runtime_available
    assert check_runtime_available("claude") is True


def test_check_runtime_available_transformers_imports(monkeypatch):
    """transformers + torch + qwen_omni_utils 다 import 가능하면 True."""
    import sys
    from screen_recorder.agent.models import check_runtime_available

    monkeypatch.setitem(sys.modules, "transformers", object())
    monkeypatch.setitem(sys.modules, "torch", object())
    monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())
    assert check_runtime_available("transformers") is True


def test_check_runtime_available_transformers_missing_returns_false(monkeypatch):
    """transformers / torch / qwen_omni_utils 중 하나라도 없으면 False."""
    import sys
    from screen_recorder.agent.models import check_runtime_available

    monkeypatch.setitem(sys.modules, "transformers", object())
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.delitem(sys.modules, "qwen_omni_utils", raising=False)

    import builtins
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name in ("torch", "qwen_omni_utils"):
            raise ImportError(f"mock — {name} not available")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert check_runtime_available("transformers") is False


def test_check_runtime_available_unknown_runtime_false():
    from screen_recorder.agent.models import check_runtime_available
    assert check_runtime_available("llama-cpp") is False
    assert check_runtime_available("unknown") is False


def test_metadata_has_tool_strategy_field():
    """ModelMetadata 는 tool_strategy 필드를 갖는다 ('none' / 'official' / 'prompted')."""
    m = ModelMetadata(
        id="x", display_name="x", runtime="transformers", repo_id="org/x",
        modalities=frozenset({"text"}), supports_korean=True,
        estimated_size_gb=1.0, estimated_vram_gb=1.0,
        context_window=1024, supports_tools=True,
        description="x",
        tool_strategy="official",
    )
    assert m.tool_strategy == "official"


def test_metadata_tool_strategy_defaults_to_none():
    m = ModelMetadata(
        id="x", display_name="x", runtime="claude", repo_id=None,
        modalities=frozenset({"text"}), supports_korean=True,
        estimated_size_gb=0, estimated_vram_gb=0,
        context_window=1000, supports_tools=False,
        description="x",
    )
    assert m.tool_strategy == "none"


def test_registry_contains_qwen_instruct_text_only():
    """Qwen2.5-7B-Instruct — text only, tool_strategy='official'."""
    from screen_recorder.agent.models.registry import ModelRegistry
    reg = ModelRegistry()
    m = reg.get("qwen25-7b-instruct")
    assert m is not None
    assert m.runtime == "transformers"
    assert m.repo_id == "Qwen/Qwen2.5-7B-Instruct"
    assert m.tool_strategy == "official"
    assert m.modalities == frozenset({"text"})
    assert m.supports_tools is True


def test_registry_qwen_omni_uses_prompted_tool_strategy():
    """Qwen2.5-Omni-7B 는 chat_template 에 tool 없음 → prompted 시뮬레이션."""
    from screen_recorder.agent.models.registry import ModelRegistry
    reg = ModelRegistry()
    m = reg.get("qwen25-omni-7b")
    assert m is not None
    assert m.tool_strategy == "prompted"
