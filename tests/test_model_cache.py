"""is_model_cached — HF 캐시 dir 검사 단위 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from screen_recorder.agent.models import is_model_cached


def test_returns_true_when_repo_in_cache(monkeypatch):
    """huggingface_hub.scan_cache_dir 가 해당 repo_id 반환하면 True."""
    fake_repo = MagicMock()
    fake_repo.repo_id = "Qwen/Qwen2.5-Omni-7B"
    fake_info = MagicMock()
    fake_info.repos = [fake_repo]

    import sys
    fake_hub = MagicMock()
    fake_hub.scan_cache_dir = MagicMock(return_value=fake_info)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    assert is_model_cached("Qwen/Qwen2.5-Omni-7B") is True


def test_returns_false_when_repo_missing(monkeypatch):
    fake_info = MagicMock()
    fake_info.repos = []

    import sys
    fake_hub = MagicMock()
    fake_hub.scan_cache_dir = MagicMock(return_value=fake_info)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    assert is_model_cached("Qwen/Qwen2.5-Omni-7B") is False


def test_returns_false_when_huggingface_hub_missing(monkeypatch):
    """huggingface_hub 자체 미설치 → False."""
    import sys, builtins
    monkeypatch.delitem(sys.modules, "huggingface_hub", raising=False)
    original_import = builtins.__import__
    def _no_hub(name, *args, **kwargs):
        if name == "huggingface_hub" or name.startswith("huggingface_hub."):
            raise ImportError("mock")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _no_hub)
    assert is_model_cached("Qwen/Qwen2.5-Omni-7B") is False


def test_handles_scan_cache_dir_exception(monkeypatch):
    """scan_cache_dir 가 raise (캐시 손상 등) → False (panic 방지)."""
    import sys
    fake_hub = MagicMock()
    fake_hub.scan_cache_dir = MagicMock(side_effect=RuntimeError("cache corrupt"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    assert is_model_cached("Qwen/Qwen2.5-Omni-7B") is False
