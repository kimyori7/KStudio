"""ChatPanel 모델 콤보 — ModelRegistry 기반 + 의존성 가드 시 fallback.

sub-plan 3 Phase 3a Task 4 — 콤보가 built-in 4개 (Sonnet/Opus/Haiku/Qwen) 표시.
Qwen 의존성 미설치 시 항목에 "(설치 필요)" 마킹 + 선택 시 set_model 가드로 콤보 fallback.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def chat_panel(qtbot, tmp_path):
    """ChatPanel + AgentRuntime 인스턴스 (start 안 함 — 위젯 검증만)."""
    from screen_recorder.ui.agent.chat_panel import ChatPanel
    from screen_recorder.agent.runtime import AgentRuntime

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__noop"])

    rt = AgentRuntime(video_tools=vt, model="claude-sonnet-4-6", cwd=tmp_path)
    panel = ChatPanel(agent=rt)
    qtbot.addWidget(panel)
    yield panel, rt


def test_combo_lists_all_models_from_registry(chat_panel):
    """콤보가 ModelRegistry 의 built-in 4개 다 표시."""
    panel, _ = chat_panel
    combo = panel._model_combo
    ids = [combo.itemData(i) for i in range(combo.count())]
    assert "claude-sonnet-4-6" in ids
    assert "claude-opus-4-7" in ids
    assert "claude-haiku-4-5-20251001" in ids
    assert "qwen25-omni-7b" in ids
    assert combo.count() == 4


def test_combo_marks_qwen_as_install_required_or_normal(chat_panel):
    """transformers 미설치 시 Qwen 항목 display 에 '(설치 필요)' — 설치 시는 정상."""
    panel, _ = chat_panel
    combo = panel._model_combo
    qwen_idx = None
    for i in range(combo.count()):
        if combo.itemData(i) == "qwen25-omni-7b":
            qwen_idx = i
            break
    assert qwen_idx is not None
    qwen_text = combo.itemText(qwen_idx)

    from screen_recorder.agent.models import check_runtime_available
    if check_runtime_available("transformers"):
        assert "(설치 필요)" not in qwen_text
    else:
        assert "(설치 필요)" in qwen_text


def test_selecting_qwen_without_deps_falls_back(chat_panel, monkeypatch, qtbot):
    """Qwen 선택 → set_model 가드 → model 유지 → 콤보 fallback."""
    import builtins
    panel, rt = chat_panel
    rt.start()
    try:
        original_import = builtins.__import__
        def _no_torch(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils"):
                raise ImportError(f"mock — {name} not available")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_torch)

        combo = panel._model_combo
        initial_id = combo.currentData()
        assert initial_id == "claude-sonnet-4-6"

        qwen_idx = None
        for i in range(combo.count()):
            if combo.itemData(i) == "qwen25-omni-7b":
                qwen_idx = i
                break

        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(50)

        # runtime model 변경 안 됨 (가드).
        assert rt._model == "claude-sonnet-4-6"
        # 콤보 fallback — sonnet 으로 복원.
        assert combo.currentData() == "claude-sonnet-4-6"
    finally:
        rt.stop()
