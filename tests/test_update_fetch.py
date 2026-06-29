import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from screen_recorder.app.updater.fetch import fetch_manifest
from screen_recorder.app.updater.manifest import ManifestError

_BODY = json.dumps({
    "version": "0.1.5", "notes": "n",
    "full_url": "https://x/Setup.exe", "full_sha256": "a" * 64,
}).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    body = _BODY
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):  # noqa: D401 — 테스트 잡음 억제
        pass


def _serve(body=_BODY, status=200):
    _Handler.body, _Handler.status = body, status
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/latest.json"


def test_fetch_manifest_ok():
    srv, url = _serve()
    try:
        m = fetch_manifest(url)
        assert m.version == "0.1.5"
    finally:
        srv.shutdown()


def test_fetch_manifest_bad_json_raises():
    srv, url = _serve(body=b"not json")
    try:
        with pytest.raises(ManifestError):
            fetch_manifest(url)
    finally:
        srv.shutdown()
