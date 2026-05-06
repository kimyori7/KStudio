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
    """MCP 가 켜진 채로 시작하는 MainWindow + 브리지.

    사용자 실제 KStudio 폴더가 자동으로 라이브러리에 채워지지 않도록 image/video
    저장 폴더를 tmp_path 로 격리한다.
    """
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path / "img")
    s.general.output_dir = str(tmp_path / "vid")
    s.mcp.enabled = True
    s.mcp.token = generate_token()
    s.mcp.port = 0   # OS 자동 할당
    win = MainWindow(s, f)
    qtbot.addWidget(win)
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


def test_call_without_token_rejected(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_current_image_path",
        json={},
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


def test_tools_list_includes_stage2_tools(bridge):
    r = requests.get(
        f"{_base(bridge)}/mcp/v1/tools",
        headers=_auth_headers(bridge), timeout=5,
    )
    names = {t["name"] for t in r.json()["tools"]}
    expected = {
        "get_current_image_path", "list_library", "list_tabs",
        "get_current_mode", "get_save_dirs", "get_settings_summary",
    }
    assert expected.issubset(names)


def test_call_list_library_empty(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_library",
        headers=_auth_headers(bridge), json={},
    )
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["entries"] == []
    assert res["total"] == 0


def test_call_list_library_after_capture(bridge, qtbot):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_library",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["total"] == 1
    e = res["entries"][0]
    assert e["kind"] == "image"
    assert e["source_label"] == "region"
    assert e["has_thumbnail"] is True


def test_call_list_library_kind_filter(bridge, qtbot):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_library",
        headers=_auth_headers(bridge), json={"kind": "video"},
    )
    assert r.json()["result"]["total"] == 0
    r2 = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_library",
        headers=_auth_headers(bridge), json={"kind": "image"},
    )
    assert r2.json()["result"]["total"] == 1


def test_call_list_tabs_empty(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_tabs",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["active_index"] == -1
    assert res["tabs"] == []


def test_call_list_tabs_after_capture(bridge, qtbot):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/list_tabs",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["total"] == 1
    assert res["active_index"] == 0
    t = res["tabs"][0]
    assert t["kind"] == "image"
    assert t["entry_id"] is not None


def test_call_get_current_mode(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_current_mode",
        headers=_auth_headers(bridge), json={},
    )
    assert r.json()["result"]["mode"] in {"image", "video"}


def test_call_get_save_dirs(bridge, qtbot, tmp_path):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_save_dirs",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert Path(res["image_dir"]).resolve() == (tmp_path / "img").resolve()
    assert Path(res["video_dir"]).resolve() == (tmp_path / "vid").resolve()
    assert res["image_format"] == "png"
    assert res["image_filename_pattern"]


def test_call_get_settings_summary_no_token(bridge, qtbot):
    """settings summary 에 토큰 같은 민감정보가 절대 안 나오도록 확인."""
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_settings_summary",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    serialized = repr(res)
    assert bridge.app_settings.mcp.token not in serialized
    assert "token" not in res
    # 핵심 메타는 포함
    assert "image_dir" in res
    assert "current_mode" in res


# ---------- Stage 4 명령 도구 ----------

def test_call_open_image_path_round_trip(bridge, qtbot, tmp_path):
    """저장된 PNG 를 open_image_path 로 다시 열 수 있어야 한다."""
    bridge._on_screenshot_captured(_img(), "region")
    bridge._save_current_screenshot()
    saved = list((tmp_path / "img").glob("*.png"))[0]
    # 새 캡처 → 다른 탭이 활성. 그 다음 open 으로 saved 다시 열기.
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/open_image_path",
        headers=_auth_headers(bridge), json={"path": str(saved)},
    )
    res = r.json()["result"]
    assert res["success"] is True
    assert Path(res["opened_path"]).resolve() == saved.resolve()


def test_call_open_image_path_rejects_missing(bridge, qtbot, tmp_path):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/open_image_path",
        headers=_auth_headers(bridge),
        json={"path": str(tmp_path / "no_such.png")},
    )
    res = r.json()["result"]
    assert res["success"] is False
    assert "없음" in res["error"] or "not" in res["error"].lower()


def test_call_open_image_path_rejects_relative(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/open_image_path",
        headers=_auth_headers(bridge),
        json={"path": "relative.png"},
    )
    assert r.json()["result"]["success"] is False


def test_call_save_current_tab_no_tab(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/save_current_tab",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["success"] is False


def test_call_save_current_tab_creates_file(bridge, qtbot, tmp_path):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/save_current_tab",
        headers=_auth_headers(bridge), json={},
    )
    res = r.json()["result"]
    assert res["success"] is True
    assert Path(res["saved_path"]).exists()


def test_call_set_mode_round_trip(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/set_mode",
        headers=_auth_headers(bridge), json={"mode": "video"},
    )
    res = r.json()["result"]
    assert res["success"] is True
    assert res["current_mode"] == "video"
    r2 = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/set_mode",
        headers=_auth_headers(bridge), json={"mode": "image"},
    )
    assert r2.json()["result"]["current_mode"] == "image"


def test_call_set_mode_rejects_unknown(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/set_mode",
        headers=_auth_headers(bridge), json={"mode": "wat"},
    )
    assert r.json()["result"]["success"] is False


def test_call_resize_image_creates_new_file(bridge, qtbot, tmp_path):
    bridge._on_screenshot_captured(_img(), "region")
    bridge._save_current_screenshot()
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/resize_image",
        headers=_auth_headers(bridge),
        json={"target_w": 80, "target_h": 60},
    )
    res = r.json()["result"]
    assert res["success"] is True
    assert res["width"] == 80
    assert res["height"] == 60
    assert Path(res["saved_path"]).exists()


def test_call_resize_image_rejects_bad_input(bridge, qtbot):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/resize_image",
        headers=_auth_headers(bridge),
        json={"target_w": -1, "target_h": 100},
    )
    assert r.json()["result"]["success"] is False


def test_call_get_request_status_unknown(bridge, qtbot):
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/get_request_status",
        headers=_auth_headers(bridge),
        json={"request_id": "no_such"},
    )
    res = r.json()["result"]
    assert "error" in res
    assert "unknown" in res["error"]


def test_pending_request_lifecycle(bridge):
    """PendingRequestStore 단위 동작."""
    store = bridge._mcp_request_store
    rid = store.create("test_tool")
    req = store.get(rid)
    assert req is not None
    assert req.status == "pending"
    store.complete(rid, {"foo": "bar"})
    assert store.get(rid).status == "done"
    assert store.get(rid).result == {"foo": "bar"}
    # complete 후엔 fail 이 무시돼야
    store.fail(rid, "too late")
    assert store.get(rid).status == "done"


def test_call_ai_upscale_returns_request_id(bridge, qtbot):
    """ai_upscale 은 즉시 request_id 반환 (pending 상태). 실제 모델 추론은 검증 X."""
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/ai_upscale",
        headers=_auth_headers(bridge),
        json={"target_w": 200, "target_h": 150},
    )
    res = r.json()["result"]
    assert res["success"] is True
    assert "request_id" in res
    assert res["status"] == "pending"


def test_call_ai_upscale_rejects_downscale(bridge, qtbot):
    bridge._on_screenshot_captured(_img(), "region")
    r = _post_with_events(
        qtbot,
        f"{_base(bridge)}/mcp/v1/call/ai_upscale",
        headers=_auth_headers(bridge),
        json={"target_w": 20, "target_h": 15},
    )
    res = r.json()["result"]
    assert res["success"] is False


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
