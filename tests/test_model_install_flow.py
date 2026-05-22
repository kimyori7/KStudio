"""ModelInstallController — fallback / dep check / download trigger 분리 검증.

Task 6 Step 2 — controller API 안정화 테스트 (2개 시작).
후속 케이스: begin_install / begin_download 이동 후 추가 예정.
"""
from __future__ import annotations

import pytest


def test_controller_emits_fallback_when_runtime_missing(qapp, monkeypatch):
    """런타임 의존성 미설치 → fallback_requested(previous_model_id) 발화 + False 반환."""
    from screen_recorder.ui.agent.model_install_flow import ModelInstallController

    monkeypatch.setattr(
        "screen_recorder.ui.agent.model_install_flow.check_runtime_available",
        lambda rt: False,
    )

    # PySide6 QObject.__init__ 는 parent 로 실제 QObject 또는 None 만 허용.
    ctl = ModelInstallController(parent_widget=None)
    fallback_signals: list[str] = []
    ctl.fallback_requested.connect(lambda mid: fallback_signals.append(mid))

    handled = ctl.handle_runtime_check(
        target_model_id="qwen25-omni-7b",
        previous_model_id="claude-sonnet-4-6",
    )
    assert handled is False
    assert fallback_signals == ["claude-sonnet-4-6"]


def test_controller_returns_true_when_runtime_available(qapp, monkeypatch):
    """런타임 의존성 설치 완료 → True 반환, fallback_requested 미발화."""
    from screen_recorder.ui.agent.model_install_flow import ModelInstallController

    monkeypatch.setattr(
        "screen_recorder.ui.agent.model_install_flow.check_runtime_available",
        lambda rt: True,
    )
    ctl = ModelInstallController(parent_widget=None)
    fallback_signals: list[str] = []
    ctl.fallback_requested.connect(lambda mid: fallback_signals.append(mid))

    handled = ctl.handle_runtime_check(
        target_model_id="qwen3-8b-ollama",
        previous_model_id="claude-sonnet-4-6",
    )
    assert handled is True
    assert fallback_signals == []


def test_controller_emits_fallback_for_unknown_model_id(qapp, monkeypatch):
    """레지스트리에 없는 모델 ID → 런타임 체크 없이 즉시 fallback."""
    from screen_recorder.ui.agent.model_install_flow import ModelInstallController

    # check_runtime_available 이 호출되면 안 됨.
    called: list[str] = []
    monkeypatch.setattr(
        "screen_recorder.ui.agent.model_install_flow.check_runtime_available",
        lambda rt: called.append(rt) or True,
    )

    ctl = ModelInstallController(parent_widget=None)
    fallback_signals: list[str] = []
    ctl.fallback_requested.connect(lambda mid: fallback_signals.append(mid))

    handled = ctl.handle_runtime_check(
        target_model_id="unknown-model-xyz",
        previous_model_id="claude-sonnet-4-6",
    )
    assert handled is False
    assert fallback_signals == ["claude-sonnet-4-6"]
    # 레지스트리 miss → 런타임 체크 불필요.
    assert called == []
