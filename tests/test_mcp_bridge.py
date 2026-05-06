"""KStudio MCP HTTP 브리지 통합 테스트.

실제로 HTTP 서버를 띄우고 `requests` 로 호출해 라우팅 / 토큰 인증 / UI 스레드
마샬링이 모두 정상 작동하는지 검증한다. UI 스레드 = 테스트 메인 스레드 (qtbot 가
이벤트 루프 처리).
"""
from __future__ import annotations
from pathlib import Path

import pytest
import requests
from PySide6.QtGui import QImage

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow
from screen_recorder.mcp.bridge_server import BridgeServer, generate_token
from screen_recorder.mcp.ui_dispatcher import UIDispatcher


def _img() -> QImage:
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def bridge(qtbot, tmp_path):
    """MCP 가 켜진 채로 시작하는 MainWindow + 브리지."""
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    s.mcp.enabled = True
    s.mcp.token = generate_token()
    s.mcp.port = 0   # OS 자동 할당
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    # 브리지가 자동 시작됐어야 한다.
    assert win._mcp_bridge is not None
    assert win._mcp_bridge.is_running
    yield win
    win._stop_mcp_bridge()


def _base(win: MainWindow) -> str:
    return f"http://127.0.0.1:{win._mcp_bridge.actual_port}"


def _auth_headers(win: MainWindow) -> dict:
    return {"Authorization": f"Bearer {win.app_settings.mcp.token}"}


def _post_with_events(qtbot, url, **kwargs):
    """도구 호출은 UI 스레드 마샬링이 필요 — 별도 스레드에서 HTTP 호출하고
    이 스레드는 Qt 이벤트 루프를 계속 돌려야 dispatcher 슬롯이 실행된다.

    `requests.post` 를 메인 스레드에서 직접 부르면 메인 스레드가 블록돼
    QueuedConnection 슬롯이 영영 처리되지 않고 dispatcher 가 timeout 한다.
    """
    import threading
    holder = {"resp": None, "err": None}

    def run():
        try:
            holder["resp"] = requests.post(url, timeout=10, **kwargs)
        except Exception as e:   # noqa: BLE001
            holder["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=10000)
    if holder["err"] is not None:
        raise holder["err"]
    return holder["resp"]


# ---------- 헬스체크 + 인증 ----------

def test_health_no_token_required(bridge):
    r = requests.get(f"{_base(bridge)}/mcp/v1/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_tools_requires_token(bridge):
    r = requests.get(f"{_base(bridge)}/mcp/v1/tools", timeout=5)
    assert r.status_code == 401


def test_tools_accepts_bearer(bridge):
    r = requests.get(
        f"{_base(bridge)}/mcp/v1/tools",
        headers=_auth_headers(bridge), timeout=5,
    )
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert any(t["name"] == "get_current_image_path" for t in tools)


def test_tools_accepts_query_token(bridge):
    """일부 CLI 는 헤더 설정이 까다로워 ?token= 폴백 지원."""
    r = requests.get(
        f"{_base(bridge)}/mcp/v1/tools",
        params={"token": bridge.app_settings.mcp.token},
        timeout=5,
    )
    assert r.status_code == 200


def test_wrong_token_rejected(bridge):
    r = requests.get(
        f"{_base(bridge)}/mcp/v1/tools",
        headers={"Authorization": "Bearer wrong"}, timeout=5,
    )
    assert r.status_code == 401


def test_unknown_path_returns_404(bridge):
    r = requests.get(
        f"{_base(bridge)}/mcp/v1/wat",
        headers=_auth_headers(bridge), timeout=5,
    )
    assert r.status_code == 404


# ---------- 도구 호출 ----------

def test_call_get_current_image_path_no_tab(bridge, qtbot):
    """탭이 없을 때는 has_tab=False."""
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        headers=_auth_headers(bridge), json={},
    )
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["has_tab"] is False
    assert res["path"] is None


def test_call_get_current_image_path_with_capture(bridge, qtbot):
    """캡처 후 호출하면 미저장 탭의 메타가 들어와야."""
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        headers=_auth_headers(bridge), json={},
    )
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["has_tab"] is True
    assert res["width"] == 40
    assert res["height"] == 30
    assert res["path"] is None   # 저장 안 했으니


def test_call_get_current_image_path_after_save(bridge, qtbot, tmp_path):
    """저장된 탭은 path 와 display_name 이 채워져야."""
    bridge._on_screenshot_captured(_img(), "region")
    bridge._save_current_screenshot()
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["has_tab"] is True
    assert res["path"] is not None
    assert Path(res["path"]).exists()
    assert res["display_name"]


def test_call_unknown_tool_returns_404(bridge):
    r = requests.post(
        f"{_base(bridge)}/mcp/v1/call/no_such_tool",
        headers=_auth_headers(bridge), json={}, timeout=5,
    )
    assert r.status_code == 404


def test_call_invalid_json_returns_400(bridge):
    r = requests.post(
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        headers={
            **_auth_headers(bridge),
            "Content-Type": "application/json",
        },
        data=b"not-json",
        timeout=5,
    )
    assert r.status_code == 400


def test_call_without_token_rejected(bridge):
    r = requests.post(
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        json={}, timeout=5,
    )
    assert r.status_code == 401


# ---------- 라이프사이클 ----------

def test_bridge_default_disabled():
    """기본 설정은 MCP 가 꺼져 있어 브리지가 안 떠야 한다."""
    s = AppSettings()
    assert s.mcp.enabled is False
    assert s.mcp.token == ""


def test_bridge_stop_idempotent(bridge):
    """stop 두 번 호출해도 에러 없이 동작."""
    bridge._stop_mcp_bridge()
    bridge._stop_mcp_bridge()
    assert bridge._mcp_bridge is None


def test_token_is_persistent_across_settings_save_load(tmp_path):
    """토큰은 settings 에 저장돼 다음 실행에도 같은 값으로 살아야 (CLI 재등록 불필요)."""
    from screen_recorder.core.settings import save, load
    s = AppSettings()
    s.mcp.enabled = True
    s.mcp.token = "abcd1234"
    p = tmp_path / "settings.json"
    save(s, p)
    loaded = load(p)
    assert loaded.mcp.enabled is True
    assert loaded.mcp.token == "abcd1234"
