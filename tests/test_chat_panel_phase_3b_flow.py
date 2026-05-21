"""Phase 3b — ChatPanel 의 installer / download 분기 흐름.

Phase 3a 의 _on_model_changed 는 set_model 호출 후 가드 차단 시 콤보 fallback 만 수행.
Phase 3b 는 set_model 호출 *전* 에 의존성 + 캐시 체크 — 분기:

1. 의존성 없음 → GpuInstallDialog(packages=PYTORCH_PACKAGES) 띄움.
2. 의존성 OK + 캐시 미스 → ModelDownloadWindow + ModelDownloadJob 시작.
3. 둘 다 OK → 정상 set_model.

각 분기마다 콤보가 어떻게 보이는지 + 다이얼로그가 정확히 호출됐는지 검증.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal


# ============================================================
# Fake ModelDownloadJob — QObject 기반이라 .connect(...) 가 실제로 동작.
# MagicMock 으로 대체하면 connect 호출이 silent no-op 이라 후속 슬롯이
# 안 호출돼 테스트 의도 (chain) 검증 불가.
# ============================================================
class _FakeJob(QObject):
    download_progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self._repo_id = kwargs.get("repo_id", "")

    def start(self) -> None:
        # 실제 thread 안 돌림 — 진행률 polling 도 안 함.
        pass


@pytest.fixture
def chat_panel_with_agent(qtbot, tmp_path):
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


def _find_qwen_idx(combo) -> int:
    for i in range(combo.count()):
        if combo.itemData(i) == "qwen25-omni-7b":
            return i
    raise AssertionError("qwen25-omni-7b 항목이 콤보에 없음")


def test_qwen_click_without_deps_opens_installer_dialog(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """transformers 미설치 → Qwen 클릭 → installer 다이얼로그 호출."""
    import builtins
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        # 의존성 import 차단 — check_runtime_available 가 False 반환하도록.
        original_import = builtins.__import__

        def _no_torch(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils", "transformers"):
                raise ImportError(f"mock — {name} not available")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_torch)

        # GpuInstallDialog 호출 추적 — show() 만 하고 실제 pip 실행 안 함.
        opened_dialogs: list = []
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        original_dlg = gid_mod.GpuInstallDialog

        class _Spy(original_dlg):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened_dialogs.append(self)

            def exec(self):
                return 0

            def show(self):
                # 실제 윈도우 띄우지 않음 — 테스트 환경에서 빈 윈도우 잔존 방지.
                pass

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _Spy)
        # chat_panel.py 안 module-level import 도 patch (alias 가 있을 수 있어 양쪽).
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _Spy)

        combo = panel._model_combo
        qwen_idx = _find_qwen_idx(combo)
        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(100)

        # 다이얼로그 1회 호출 + PyTorch 패키지로 호출됨.
        assert len(opened_dialogs) >= 1, "GpuInstallDialog 가 호출되지 않음"
        assert "torch" in opened_dialogs[0]._packages
        # 의존성 없으면 set_model 호출 안 됨 — 모델 유지.
        assert rt._model == "claude-sonnet-4-6"
    finally:
        rt.stop()


def test_qwen_click_with_deps_but_no_cache_opens_download(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """의존성 OK + 모델 미캐시 → 다운로드 윈도우."""
    import sys
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        # 의존성 import 성공처럼 보이게 — sys.modules 에 더미 객체 주입.
        monkeypatch.setitem(sys.modules, "transformers", object())
        monkeypatch.setitem(sys.modules, "torch", object())
        monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())

        # is_model_cached 가 False 반환 → 다운로드 분기.
        # chat_panel 이 module-level alias 로 부르므로 양쪽 다 patch (양쪽 다 동작 보장).
        monkeypatch.setattr(
            "screen_recorder.agent.models.cache.is_model_cached",
            lambda repo_id: False,
        )
        monkeypatch.setattr(
            "screen_recorder.agent.models.is_model_cached",
            lambda repo_id: False,
        )
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "is_model_cached"):
            monkeypatch.setattr(cp_mod, "is_model_cached", lambda repo_id: False)

        opened: list = []
        from screen_recorder.ui import model_download_window as mdw_mod
        original = mdw_mod.ModelDownloadWindow

        class _Spy(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened.append(self)

            def show(self):
                pass

        monkeypatch.setattr(mdw_mod, "ModelDownloadWindow", _Spy)
        if hasattr(cp_mod, "ModelDownloadWindow"):
            monkeypatch.setattr(cp_mod, "ModelDownloadWindow", _Spy)

        # ModelDownloadJob 도 mock — 실제 thread 안 돌리게.
        from screen_recorder.agent.models import downloader as dl_mod
        monkeypatch.setattr(dl_mod, "ModelDownloadJob", _FakeJob)
        if hasattr(cp_mod, "ModelDownloadJob"):
            monkeypatch.setattr(cp_mod, "ModelDownloadJob", _FakeJob)
        # registry 경로 alias 도 — 안전망.
        from screen_recorder.agent import models as models_mod
        if hasattr(models_mod, "ModelDownloadJob"):
            monkeypatch.setattr(models_mod, "ModelDownloadJob", _FakeJob)

        combo = panel._model_combo
        qwen_idx = _find_qwen_idx(combo)
        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(100)

        assert len(opened) >= 1, "ModelDownloadWindow 가 호출되지 않음"
        # 다운로드 분기 — set_model 아직 호출 안 됨 (다운로드 완료 후 chain).
        assert rt._model == "claude-sonnet-4-6"
    finally:
        rt.stop()


def test_installer_rejected_after_success_does_not_fallback(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """설치 성공 후 사용자가 다이얼로그 닫음 → 콤보 fallback 안 됨 (idempotency).

    GpuInstallDialog 의 close_btn 은 accept() 가 아닌 close() — 항상 rejected 발화.
    finished_ok 이후의 rejected 를 fallback 으로 처리하면 모델/UI 불일치 발생.
    """
    import builtins
    import sys
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        original_import = builtins.__import__
        deps_present = {"value": False}

        # importlib.import_module 가 builtins.__import__ 를 거침 — 처음엔 ImportError,
        # 설치 성공 후엔 sys.modules 의 stub 으로 통과시키게.
        def _conditional(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils", "transformers"):
                if deps_present["value"] and name in sys.modules:
                    return sys.modules[name]
                if deps_present["value"]:
                    return original_import(name, *args, **kwargs)
                raise ImportError(f"mock — {name} not available")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _conditional)

        opened: list = []
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        original_dlg = gid_mod.GpuInstallDialog

        class _Spy(original_dlg):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened.append(self)

            def show(self):
                pass

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _Spy)
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _Spy)

        # 의존성 OK 로 전환된 후 캐시 hit 시나리오 — chain 이 set_model 까지 가게.
        monkeypatch.setattr(
            "screen_recorder.agent.models.cache.is_model_cached",
            lambda repo_id: True,
        )
        monkeypatch.setattr(
            "screen_recorder.agent.models.is_model_cached",
            lambda repo_id: True,
        )
        if hasattr(cp_mod, "is_model_cached"):
            monkeypatch.setattr(cp_mod, "is_model_cached", lambda repo_id: True)

        combo = panel._model_combo
        qwen_idx = _find_qwen_idx(combo)
        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(50)

        assert len(opened) == 1
        dlg = opened[0]

        # 설치 성공 시나리오 — sys.modules 에 stub 주입 후 finished_ok 발화.
        monkeypatch.setitem(sys.modules, "transformers", object())
        monkeypatch.setitem(sys.modules, "torch", object())
        monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())
        deps_present["value"] = True
        dlg.finished_ok.emit()
        qtbot.wait(50)

        # 설치 + 캐시 hit → set_model 정상 진행 → qwen 으로 변경됨.
        assert rt._model == "qwen25-omni-7b"
        assert combo.currentData() == "qwen25-omni-7b"

        # 이제 사용자가 다이얼로그 [닫기] → rejected 발화.
        # idempotency 가드가 동작해 fallback 안 일어나야 함.
        dlg.rejected.emit()
        qtbot.wait(50)

        # 콤보/모델 모두 qwen 유지 (fallback 시 sonnet 으로 돌아갔을 것).
        assert rt._model == "qwen25-omni-7b"
        assert combo.currentData() == "qwen25-omni-7b"
    finally:
        rt.stop()


def test_qwen_click_with_deps_and_cache_proceeds_normally(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """의존성 OK + 모델 캐시 OK → set_model 정상 진행, 다이얼로그 X."""
    import sys
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        # 의존성 OK.
        monkeypatch.setitem(sys.modules, "transformers", object())
        monkeypatch.setitem(sys.modules, "torch", object())
        monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())
        # 캐시 hit.
        monkeypatch.setattr(
            "screen_recorder.agent.models.cache.is_model_cached",
            lambda repo_id: True,
        )
        monkeypatch.setattr(
            "screen_recorder.agent.models.is_model_cached",
            lambda repo_id: True,
        )
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "is_model_cached"):
            monkeypatch.setattr(cp_mod, "is_model_cached", lambda repo_id: True)

        # 다이얼로그가 떠선 안 됨 — 호출되면 즉시 fail 하도록 patch.
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        from screen_recorder.ui import model_download_window as mdw_mod

        def _fail_dlg(*args, **kwargs):
            raise AssertionError("GpuInstallDialog 가 떠선 안 됨")

        def _fail_win(*args, **kwargs):
            raise AssertionError("ModelDownloadWindow 가 떠선 안 됨")

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _fail_dlg)
        monkeypatch.setattr(mdw_mod, "ModelDownloadWindow", _fail_win)
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _fail_dlg)
        if hasattr(cp_mod, "ModelDownloadWindow"):
            monkeypatch.setattr(cp_mod, "ModelDownloadWindow", _fail_win)

        combo = panel._model_combo
        qwen_idx = _find_qwen_idx(combo)
        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(100)

        # 정상 set_model — agent 의 _model 이 qwen 으로 변경.
        assert rt._model == "qwen25-omni-7b"
    finally:
        rt.stop()
