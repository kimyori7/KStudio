"""HTTPS opener — 사내망 TLS(truststore) 대응. fetch/download 공용."""
from __future__ import annotations

import urllib.request

_truststore_injected = False


def ensure_truststore() -> None:
    """OS 인증서 저장소로 TLS 검증(사내 프록시 대응). 프로세스 전역·한 번만·best-effort.

    (기존 ytdlp_runner / background_removal 의 _ensure_truststore 와 동일 패턴.)
    """
    global _truststore_injected
    if _truststore_injected:
        return
    _truststore_injected = True
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:   # noqa: BLE001 — 미설치/실패해도 일반 네트워크는 동작
        pass


def open_url(url: str, timeout: float = 30.0):
    """GET 요청 → 응답(컨텍스트 매니저). truststore 를 먼저 활성화한다."""
    ensure_truststore()
    req = urllib.request.Request(url, headers={"User-Agent": "KStudio-Updater"})
    return urllib.request.urlopen(req, timeout=timeout)   # noqa: S310 — https 고정
