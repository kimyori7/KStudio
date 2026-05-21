"""runtime.py 의 backend factory 단위 테스트.

sub-plan 3 Phase 3a Task 2:
- _create_backend(model_id) factory 가 ModelRegistry 메타데이터 (runtime 필드) 로
  ClaudeBackend / TransformersBackend 분기.
- __init__ 도 factory 사용 (하드코딩 X) — 초기 model 이 qwen 이면 TransformersBackend.
- 의존성 가드는 Task 3 (set_model 진입점) — 이 Task 는 factory 만.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from screen_recorder.agent.runtime import AgentRuntime
from screen_recorder.agent.backends import ClaudeBackend, TransformersBackend


@pytest.fixture
def video_tools_mock():
    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__noop"])
    return vt


def test_factory_returns_claude_backend_for_claude_models(qtbot, video_tools_mock):
    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    backend = rt._create_backend("claude-sonnet-4-6")
    assert isinstance(backend, ClaudeBackend)


def test_factory_returns_transformers_backend_for_qwen(qtbot, video_tools_mock):
    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    backend = rt._create_backend("qwen25-omni-7b")
    assert isinstance(backend, TransformersBackend)
    assert backend._repo_id == "Qwen/Qwen2.5-Omni-7B"


def test_factory_raises_for_unknown_model(qtbot, video_tools_mock):
    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    with pytest.raises(ValueError, match="unknown model"):
        rt._create_backend("nonexistent-model")


def test_init_creates_claude_backend_by_default(qtbot, video_tools_mock):
    """기본 모델 = claude-sonnet-4-6 — ClaudeBackend 인스턴스."""
    rt = AgentRuntime(video_tools=video_tools_mock)
    assert isinstance(rt._backend, ClaudeBackend)


def test_init_with_qwen_creates_transformers_backend(qtbot, video_tools_mock):
    """초기 모델이 Qwen 이면 TransformersBackend (의존성 가드 없이 — Task 3 에서 추가)."""
    rt = AgentRuntime(video_tools=video_tools_mock, model="qwen25-omni-7b")
    assert isinstance(rt._backend, TransformersBackend)


# ---- Task 3: set_model 진입점 의존성 가드 ----

@pytest.mark.asyncio
async def test_set_model_to_qwen_without_torch_emits_guard_and_keeps_old(
    qtbot, video_tools_mock, monkeypatch,
):
    """transformers 미설치 → set_model('qwen...') → 가드 메시지 + model 유지 (변경 안 됨)."""
    import builtins
    from screen_recorder.agent.runtime import AgentMessage

    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    rt.start()
    try:
        # transformers / torch import 실패 시뮬레이션.
        original_import = builtins.__import__
        def _no_torch(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils"):
                raise ImportError(f"mock — {name} not available")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_torch)

        received: list = []
        rt.message_received.connect(lambda m: received.append(m))

        rt.set_model("qwen25-omni-7b")

        # qtbot 으로 시그널 처리 대기.
        qtbot.wait(50)

        # 가드 메시지 emit.
        sys_msgs = [m for m in received if isinstance(m, AgentMessage) and m.role == "system"]
        assert len(sys_msgs) >= 1
        assert "PyTorch" in sys_msgs[0].text or "설치" in sys_msgs[0].text

        # model 변경 안 됨 — fallback.
        assert rt._model == "claude-sonnet-4-6"
    finally:
        rt.stop()


@pytest.mark.asyncio
async def test_set_model_to_qwen_with_deps_proceeds(
    qtbot, video_tools_mock, monkeypatch,
):
    """의존성 다 있으면 set_model 정상 진행 → backend 교체."""
    import sys
    monkeypatch.setitem(sys.modules, "transformers", object())
    monkeypatch.setitem(sys.modules, "torch", object())
    monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())

    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    rt.start()
    try:
        rt.set_model("qwen25-omni-7b")
        assert rt._model == "qwen25-omni-7b"
        from screen_recorder.agent.backends import TransformersBackend
        assert isinstance(rt._backend, TransformersBackend)
    finally:
        rt.stop()


def test_set_model_between_claude_variants_skips_dep_check(qtbot, video_tools_mock):
    """같은 runtime (claude → claude) 전환은 dep check 안 함 (의미 없음)."""
    rt = AgentRuntime(video_tools=video_tools_mock, model="claude-sonnet-4-6")
    rt.start()
    try:
        rt.set_model("claude-haiku-4-5-20251001")
        assert rt._model == "claude-haiku-4-5-20251001"
    finally:
        rt.stop()
