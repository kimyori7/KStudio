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


def test_combo_lists_only_non_claude_models(chat_panel):
    """콤보가 ModelRegistry 의 non-Claude 항목만 표시 (Claude 는 UI 노출 안 함)."""
    panel, _ = chat_panel
    combo = panel._model_combo
    ids = [combo.itemData(i) for i in range(combo.count())]
    # Claude 계열은 filter 됨 — registry 에는 있지만 콤보엔 없음.
    assert "claude-sonnet-4-6" not in ids
    assert "claude-opus-4-7" not in ids
    assert "claude-haiku-4-5-20251001" not in ids
    # 로컬 Qwen 시리즈는 모두 노출.
    assert "qwen25-7b-instruct" in ids
    assert "qwen25-omni-7b" in ids
    assert "qwen3-vl-2b-instruct" in ids
    assert "qwen3-vl-4b-instruct" in ids
    assert "qwen3-8b-ollama" in ids


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


def test_selecting_qwen_without_deps_opens_installer_keeps_model(
    chat_panel, monkeypatch, qtbot,
):
    """Qwen 선택 + 의존성 없음 → installer 다이얼로그 + 모델 유지.

    Phase 3a 동작 (즉시 fallback) → Phase 3b 동작 (다이얼로그 띄움 + 콤보는 Qwen 유지,
    cancel/실패 시 fallback). 정밀 다이얼로그 검증은 test_chat_panel_phase_3b_flow.py.
    여기서는 runtime model 이 변경되지 않는다는 점만 확인.
    """
    panel, rt = chat_panel
    rt.start()
    try:
        # torch / qwen_omni_utils 가 실제 venv 에 있어도 (테스트 환경) "없는 것처럼"
        # 처리 — check_runtime_available 을 직접 patch (builtins.__import__ patch 는
        # sys.modules 캐시 때문에 안 통함).
        def _no_transformers(runtime):
            return runtime == "claude"
        for path in (
            "screen_recorder.agent.models.registry.check_runtime_available",
            "screen_recorder.agent.models.check_runtime_available",
            "screen_recorder.ui.agent.chat_panel.check_runtime_available",
        ):
            monkeypatch.setattr(path, _no_transformers)

        # GpuInstallDialog 가 실제로 뜨지 않게 — show() 만 no-op.
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        original_dlg = gid_mod.GpuInstallDialog

        class _SilentDlg(original_dlg):
            def show(self):
                pass

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _SilentDlg)
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _SilentDlg)

        combo = panel._model_combo
        initial_id = combo.currentData()
        # AgentRuntime 에는 claude-sonnet-4-6 (registry 항목) 이 들어 있지만,
        # ChatPanel 시작 시 Claude 는 DEFAULT_MODEL_ID 로 demote → 콤보 첫 칸이 Qwen3-VL 2B.
        assert initial_id == "qwen3-vl-2b-instruct"

        qwen_idx = None
        for i in range(combo.count()):
            if combo.itemData(i) == "qwen25-omni-7b":
                qwen_idx = i
                break

        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(50)

        # runtime model 변경 안 됨 — set_model 자체가 호출 안 됨 (installer 단계).
        assert rt._model == "claude-sonnet-4-6"
        # 콤보는 Qwen 유지 — 사용자가 다이얼로그 cancel 누르기 전까지.
        assert combo.currentData() == "qwen25-omni-7b"
    finally:
        rt.stop()
