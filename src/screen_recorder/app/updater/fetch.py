"""latest.json 가져오기 → Manifest."""
from __future__ import annotations

from screen_recorder.app.updater import net
from screen_recorder.app.updater.manifest import Manifest, parse_manifest


def fetch_manifest(url: str, timeout: float = 10.0) -> Manifest:
    """manifest 를 받아 파싱. 네트워크/형식 오류는 예외로 전파(호출자가 삼킨다)."""
    with net.open_url(url, timeout=timeout) as resp:
        raw = resp.read()
    return parse_manifest(raw)
