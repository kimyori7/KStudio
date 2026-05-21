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


# ============================================================
# 2026-05-21 사용자 보고 회귀 보호:
# "설치 완료했는데도 PyTorch 설치 다이얼로그가 여러 개 뜬다"
# 원인: pip install 후 같은 프로세스에서 importlib 가 새 패키지 인식 못 함 →
#       check_runtime_available 가 여전히 False → _on_install_ok 가 chain
#       호출 → _open_installer_for 가 또 호출 → 무한 chain.
# Fix: invalidate_caches() 후 재체크. 그래도 False 면 "재시작 안내" + chain 중단.
#      + 이미 다이얼로그 떠있으면 raise 만.
# ============================================================


def test_installer_finished_ok_but_import_still_fails_shows_restart_and_no_chain(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """설치 성공 → 같은 프로세스 import 여전히 실패 → 재시작 안내 + chain 중단.

    회귀 보호: 무한 chain (다이얼로그 여러 개 뜸) 방지.
    """
    import builtins
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        original_import = builtins.__import__
        def _no_torch(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils", "transformers"):
                raise ImportError(f"mock — {name} not available")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_torch)

        opened_dialogs: list = []
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        original_dlg = gid_mod.GpuInstallDialog

        class _Spy(original_dlg):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened_dialogs.append(self)
            def show(self): pass

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _Spy)
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _Spy)

        # 시스템 메시지 수집.
        sys_msgs: list = []
        def _capture(m):
            if getattr(m, "role", None) == "system":
                sys_msgs.append(m.text)
        original_append = panel.append_message
        def _wrap(m):
            _capture(m)
            original_append(m)
        monkeypatch.setattr(panel, "append_message", _wrap)

        combo = panel._model_combo
        qwen_idx = _find_qwen_idx(combo)
        combo.setCurrentIndex(qwen_idx)
        qtbot.wait(50)

        # 첫 dialog 떴음.
        assert len(opened_dialogs) == 1

        # 첫 dialog 의 finished_ok 시뮬레이션 — import 는 여전히 차단된 상태.
        opened_dialogs[0].finished_ok.emit()
        qtbot.wait(50)

        # 핵심 검증: 두 번째 dialog 안 떴음 (chain 중단).
        assert len(opened_dialogs) == 1, (
            f"무한 chain 회귀: dialog {len(opened_dialogs)}개 떴음 (1이어야)"
        )
        # 재시작 안내 메시지 emit.
        assert any("재시작" in t for t in sys_msgs), (
            f"재시작 안내 메시지 없음. 수신된 system msgs: {sys_msgs}"
        )
        # 콤보 fallback — sonnet 으로 복원.
        assert combo.currentData() == "claude-sonnet-4-6"
    finally:
        rt.stop()


def test_startup_demotes_qwen_to_default_when_deps_missing(qtbot, tmp_path, monkeypatch):
    """settings 가 Qwen (의존성 없음) 가리키면 시작 시 default 로 강등.

    회귀 보호 (2026-05-21 사용자 보고): "껏다 킬때마다 PyTorch 설치창 뜬다".
    원인: settings 에 Qwen 저장 → 다음 실행 시 콤보가 Qwen 으로 → 자동 트리거.
    Fix: __init__ 시점에 의존성 체크 → 없으면 default 로 강등.
    """
    import builtins
    from screen_recorder.ui.agent.chat_panel import ChatPanel, DEFAULT_MODEL_ID
    from screen_recorder.agent.runtime import AgentRuntime

    original_import = builtins.__import__
    def _no_torch(name, *args, **kwargs):
        if name in ("torch", "qwen_omni_utils", "transformers"):
            raise ImportError("mock")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _no_torch)

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__noop"])
    rt = AgentRuntime(video_tools=vt, model="claude-sonnet-4-6", cwd=tmp_path)

    # settings 에 Qwen 저장된 상태 시뮬레이션.
    panel = ChatPanel(agent=rt, initial_model_id="qwen25-omni-7b")
    qtbot.addWidget(panel)

    # 강등 확인 — 콤보가 default (Sonnet) 로 시작.
    assert panel._model_combo.currentData() == DEFAULT_MODEL_ID
    # 강등 플래그 set — 사용자 알림 대기.
    assert panel._startup_demoted_from == "Qwen2.5-Omni 7B (로컬, 멀티모달)"


def test_emit_startup_warnings_emits_demotion_message_once(qtbot, tmp_path, monkeypatch):
    """emit_startup_warnings 호출 시 강등 사실 시스템 메시지로 사용자에게 알림."""
    import builtins
    from screen_recorder.ui.agent.chat_panel import ChatPanel
    from screen_recorder.agent.runtime import AgentRuntime

    original_import = builtins.__import__
    def _no_torch(name, *args, **kwargs):
        if name in ("torch", "qwen_omni_utils", "transformers"):
            raise ImportError("mock")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _no_torch)

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__noop"])
    rt = AgentRuntime(video_tools=vt, model="claude-sonnet-4-6", cwd=tmp_path)

    panel = ChatPanel(agent=rt, initial_model_id="qwen25-omni-7b")
    qtbot.addWidget(panel)

    # 시스템 메시지 수집.
    sys_msgs: list = []
    original_append = panel.append_message
    def _wrap(m):
        if getattr(m, "role", None) == "system":
            sys_msgs.append(m.text)
        original_append(m)
    monkeypatch.setattr(panel, "append_message", _wrap)

    panel.emit_startup_warnings()
    assert len(sys_msgs) == 1
    assert "Qwen" in sys_msgs[0]
    assert "PyTorch" in sys_msgs[0] or "의존성" in sys_msgs[0]

    # 두 번 호출해도 추가 메시지 X — 한 번만.
    panel.emit_startup_warnings()
    assert len(sys_msgs) == 1


def test_startup_with_deps_ok_keeps_qwen(qtbot, tmp_path, monkeypatch):
    """의존성 OK 면 settings 의 Qwen 그대로 유지 (강등 X)."""
    import sys
    from screen_recorder.ui.agent.chat_panel import ChatPanel
    from screen_recorder.agent.runtime import AgentRuntime

    monkeypatch.setitem(sys.modules, "transformers", object())
    monkeypatch.setitem(sys.modules, "torch", object())
    monkeypatch.setitem(sys.modules, "qwen_omni_utils", object())

    vt = MagicMock()
    vt.plan_gate = MagicMock(return_value=MagicMock())
    vt.mcp_server = MagicMock(return_value=MagicMock())
    vt.tool_names = MagicMock(return_value=["mcp__kstudio_video__noop"])
    rt = AgentRuntime(video_tools=vt, model="claude-sonnet-4-6", cwd=tmp_path)

    panel = ChatPanel(agent=rt, initial_model_id="qwen25-omni-7b")
    qtbot.addWidget(panel)

    # Qwen 유지 — 강등 안 됨.
    assert panel._model_combo.currentData() == "qwen25-omni-7b"
    assert panel._startup_demoted_from is None


def test_open_installer_twice_does_not_create_second_dialog(
    chat_panel_with_agent, monkeypatch, qtbot,
):
    """이미 installer 다이얼로그 떠있는 상태에서 또 _open_installer_for 호출 → 새 dialog 안 만듦.

    회귀 보호: 사용자가 Qwen 클릭 (dialog 뜸) → 닫지 않고 콤보에서 다른 클릭 →
    또 새 dialog 뜨는 현상 방지.
    """
    import builtins
    panel, rt = chat_panel_with_agent
    rt.start()
    try:
        original_import = builtins.__import__
        def _no_torch(name, *args, **kwargs):
            if name in ("torch", "qwen_omni_utils", "transformers"):
                raise ImportError("mock")
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", _no_torch)

        opened_dialogs: list = []
        from screen_recorder.ui import gpu_install_dialog as gid_mod
        original_dlg = gid_mod.GpuInstallDialog

        class _Spy(original_dlg):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened_dialogs.append(self)
                self._spy_visible = True
            def show(self):
                # show 후 isHidden() 가 False 반환하도록 — 실제 show 안 띄움.
                self._spy_visible = True
            def isHidden(self) -> bool:
                return not self._spy_visible
            def raise_(self): pass
            def activateWindow(self): pass

        monkeypatch.setattr(gid_mod, "GpuInstallDialog", _Spy)
        from screen_recorder.ui.agent import chat_panel as cp_mod
        if hasattr(cp_mod, "GpuInstallDialog"):
            monkeypatch.setattr(cp_mod, "GpuInstallDialog", _Spy)

        # 첫 호출 — Qwen 클릭.
        meta = panel._model_registry.get("qwen25-omni-7b")
        panel._open_installer_for(meta, "claude-sonnet-4-6")
        assert len(opened_dialogs) == 1

        # 두 번째 호출 — dialog 가 살아있으니 새 인스턴스화 안 됨.
        panel._open_installer_for(meta, "claude-sonnet-4-6")
        assert len(opened_dialogs) == 1, (
            f"idempotency 회귀: dialog {len(opened_dialogs)}개 (1이어야)"
        )
    finally:
        rt.stop()
