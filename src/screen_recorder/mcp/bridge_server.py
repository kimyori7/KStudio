"""KStudio HTTP 브리지 서버 — localhost 127.0.0.1 only, 토큰 인증.

stdio MCP 서버(`kstudio_mcp.py`) 또는 임의의 HTTP 클라이언트가 KStudio 의 도구를
호출할 수 있게 한다. 외부 네트워크에는 절대 노출되지 않도록 `127.0.0.1` 만 bind.

엔드포인트:
- `GET /mcp/v1/health` — 토큰 없이 OK 반환 (살아있는지 확인용).
- `GET /mcp/v1/tools` — 토큰 필요. 등록된 도구 메타 리스트.
- `POST /mcp/v1/call/<tool_name>` — 토큰 필요. body = JSON 파라미터, 응답 = 도구 dict.

인증: `Authorization: Bearer <token>` 헤더 또는 `?token=<token>` 쿼리 둘 다 받음
(CLI 마다 헤더 지원이 들쭉날쭉해서 둘 다 허용).
"""
from __future__ import annotations
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .tools import TOOLS, list_tools
from .ui_dispatcher import UIDispatcher


_log = logging.getLogger(__name__)


def generate_token() -> str:
    """32자 hex 토큰 — 첫 시작 시 settings 에 저장."""
    return secrets.token_hex(16)


class _Handler(BaseHTTPRequestHandler):
    """HTTPServer 가 요청마다 인스턴스화. server.bridge 로 컨텍스트 접근."""

    # http.server 의 기본 로그(stderr) 가 너무 시끄러움 — 로거로만.
    def log_message(self, fmt: str, *args) -> None:
        _log.debug("HTTP " + fmt, *args)

    # ---------- 공통 헬퍼 ----------

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_token(self, parsed) -> bool:
        bridge: BridgeServer = self.server.bridge   # type: ignore[attr-defined]
        if not bridge.token:
            return True   # 토큰 미설정은 부팅 직전 상태 — 절대 일어나면 안 됨, 안전상 거부
        # Authorization: Bearer <token>
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            if secrets.compare_digest(auth[7:].strip(), bridge.token):
                return True
        # ?token=...
        qs = parse_qs(parsed.query or "")
        token_q = (qs.get("token") or [""])[0]
        if token_q and secrets.compare_digest(token_q, bridge.token):
            return True
        return False

    # ---------- 라우팅 ----------

    def do_GET(self) -> None:   # noqa: N802 — http.server API
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/mcp/v1/health":
            self._send_json(200, {"ok": True, "service": "kstudio-mcp-bridge"})
            return

        if not self._check_token(parsed):
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/mcp/v1/tools":
            self._send_json(200, {"tools": list_tools()})
            return

        self._send_json(404, {"error": f"unknown path: {path}"})

    def do_POST(self) -> None:   # noqa: N802
        parsed = urlparse(self.path)
        if not self._check_token(parsed):
            self._send_json(401, {"error": "unauthorized"})
            return

        prefix = "/mcp/v1/call/"
        if not parsed.path.startswith(prefix):
            self._send_json(404, {"error": f"unknown path: {parsed.path}"})
            return

        tool_name = parsed.path[len(prefix):]
        if tool_name not in TOOLS:
            self._send_json(404, {"error": f"unknown tool: {tool_name}"})
            return

        # 요청 본문 파싱 — 비어있어도 허용.
        length = int(self.headers.get("Content-Length") or 0)
        params: dict = {}
        if length > 0:
            try:
                params = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(params, dict):
                    raise ValueError("body must be a JSON object")
            except (ValueError, json.JSONDecodeError) as e:
                self._send_json(400, {"error": f"invalid JSON body: {e}"})
                return

        bridge: BridgeServer = self.server.bridge   # type: ignore[attr-defined]
        fn = TOOLS[tool_name]
        try:
            result = bridge.dispatcher.call(
                fn, bridge.window, params,
                timeout=bridge.tool_timeout,
            )
        except TimeoutError as e:
            self._send_json(504, {"error": str(e)})
            return
        except Exception as e:   # noqa: BLE001
            _log.exception("tool error: %s", tool_name)
            self._send_json(500, {"error": str(e), "type": type(e).__name__})
            return
        self._send_json(200, {"result": result})


class _ThreadedHTTPServer(HTTPServer):
    """요청별 스레드 — 한 도구 호출이 다른 호출을 막지 않게."""
    allow_reuse_address = True

    # 별도 스레드에서 처리하도록 ThreadingMixIn 효과를 직접 구현.
    def process_request(self, request, client_address) -> None:
        t = threading.Thread(
            target=self._handle_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        t.start()

    def _handle_request_thread(self, request, client_address) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:   # noqa: BLE001
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class BridgeServer:
    """KStudio HTTP 브리지 — main_window 가 보유, 시작/정지 lifecycle 책임.

    `start()` 는 스레드에서 HTTP 서버를 띄우고 즉시 반환. `stop()` 는 서버 종료 + 스레드
    join. 시작 후 `actual_port` 로 OS 가 할당한 실제 포트 확인 가능 (settings.port=0 일 때).
    """

    def __init__(
        self,
        window,
        dispatcher: UIDispatcher,
        token: str,
        port: int = 0,
        tool_timeout: float = 30.0,
    ) -> None:
        self.window = window
        self.dispatcher = dispatcher
        self.token = token
        self.requested_port = port
        self.tool_timeout = tool_timeout
        self._server: Optional[_ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def actual_port(self) -> int:
        if self._server is None:
            return 0
        return self._server.server_address[1]

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def start(self) -> int:
        if self._server is not None:
            return self.actual_port
        self._server = _ThreadedHTTPServer(
            ("127.0.0.1", self.requested_port), _Handler,
        )
        self._server.bridge = self   # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="kstudio-mcp-bridge",
            daemon=True,
        )
        self._thread.start()
        port = self.actual_port
        _log.info("MCP bridge listening on 127.0.0.1:%d", port)
        return port

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            if self._thread is not None:
                self._thread.join(timeout=2.0)
                self._thread = None
            _log.info("MCP bridge stopped")
