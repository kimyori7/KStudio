import hashlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from screen_recorder.app.updater.download import sha256_file, download_to

_PAYLOAD = b"KStudio-binary-bytes" * 1000
_SHA = hashlib.sha256(_PAYLOAD).hexdigest()


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(_PAYLOAD)))
        self.end_headers()
        self.wfile.write(_PAYLOAD)

    def log_message(self, *a):
        pass


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/KStudio.exe"


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(_PAYLOAD)
    assert sha256_file(f) == _SHA


def test_download_ok_and_progress(tmp_path: Path):
    srv, url = _serve()
    seen = []
    try:
        dest = tmp_path / "KStudio.exe"
        out = download_to(url, dest, _SHA, progress=lambda d, t: seen.append((d, t)))
        assert out.read_bytes() == _PAYLOAD
        assert seen and seen[-1][0] == len(_PAYLOAD)   # 마지막 콜백 = 전부 받음
    finally:
        srv.shutdown()


def test_download_sha_mismatch_deletes(tmp_path: Path):
    srv, url = _serve()
    try:
        dest = tmp_path / "KStudio.exe"
        with pytest.raises(ValueError):
            download_to(url, dest, "f" * 64)   # 틀린 해시
        assert not dest.exists()               # 폐기됨
    finally:
        srv.shutdown()


def test_download_deletes_partial_on_midstream_error(tmp_path: Path):
    # 스트리밍 도중 예외(여기선 진행 콜백이 던짐)가 나도 부분 파일을 남기지 않는다.
    srv, url = _serve()

    def boom(downloaded, total):
        raise RuntimeError("simulated mid-stream failure")

    try:
        dest = tmp_path / "KStudio.exe"
        with pytest.raises(RuntimeError):
            download_to(url, dest, _SHA, progress=boom)
        assert not dest.exists()   # 부분 파일 청소됨(검증 못 한 바이너리 안 남김)
    finally:
        srv.shutdown()
