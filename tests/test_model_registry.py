"""ModelRegistry 단위 테스트 — built-in 4개 + dependency check."""
from __future__ import annotations

import pytest

from screen_recorder.agent.models import ModelMetadata, ModelRegistry


def test_builtin_models_count_and_ids():
    """built-in 4개: Claude opus/sonnet/haiku + Qwen2.5-Omni 7B."""
    reg = ModelRegistry()
    models = reg.all_models()
    ids = [m.id for m in models]
    assert "claude-opus-4-7" in ids
    assert "claude-sonnet-4-6" in ids
    assert "claude-haiku-4-5-20251001" in ids
    assert "qwen25-omni-7b" in ids
    assert len(models) == 4


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
