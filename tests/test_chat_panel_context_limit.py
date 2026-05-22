"""_context_limit_for 가 ModelRegistry.context_window 를 single source of truth 로 사용."""
from __future__ import annotations


def test_context_limit_uses_registry_for_all_known_models():
    from screen_recorder.ui.agent.chat_panel import _context_limit_for
    from screen_recorder.agent.models.registry import ModelRegistry

    reg = ModelRegistry()
    # registry 의 모든 모델에 대해 _context_limit_for 가 registry 값 반환.
    for meta in reg.all_models():
        assert _context_limit_for(meta.id) == meta.context_window, (
            f"{meta.id}: registry={meta.context_window} vs UI={_context_limit_for(meta.id)}"
        )


def test_context_limit_unknown_model_falls_back_to_200k():
    """모르는 모델은 안전한 default — 보수적으로 큰 값."""
    from screen_recorder.ui.agent.chat_panel import _context_limit_for
    assert _context_limit_for("nonexistent-model-xyz") == 200_000
