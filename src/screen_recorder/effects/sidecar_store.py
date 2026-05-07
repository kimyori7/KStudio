"""영상 hash 계산 + 사이드카 폴더 관리.

사이드카는 KStudio 전용 폴더(예: %APPDATA%\\KStudio\\sidecars\\) 에 저장된다.
파일명은 영상 파일 첫 1MB 의 sha-1 hex(40자) + .kstudio.

영상의 첫 1MB 가 같으면 hash 충돌 가능 (드물지만). 충돌 시 source_path 가 다르면
파일명에 suffix(_2, _3, …) 붙여 새 사이드카로 저장.
"""
from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path

from .sidecar import Sidecar, save_atomic, load


HASH_PREFIX_BYTES = 1 * 1024 * 1024     # 첫 1MB
SIDECAR_EXT = ".kstudio"


def compute_video_hash(video_path: Path) -> str:
    """영상 파일 첫 1MB 의 sha-1 hex (40자). 파일 < 1MB 면 전체."""
    h = hashlib.sha1()
    with open(video_path, "rb") as f:
        h.update(f.read(HASH_PREFIX_BYTES))
    return h.hexdigest()


def default_sidecar_dir() -> Path:
    """플랫폼별 기본 사이드카 폴더.

    Windows: %APPDATA%\\KStudio\\sidecars
    Linux/macOS: ~/.config/kstudio/sidecars (향후 — 현재 win32 위주)
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "KStudio" / "sidecars"
        return Path.home() / "AppData" / "Roaming" / "KStudio" / "sidecars"
    # 비-Windows fallback
    return Path.home() / ".config" / "kstudio" / "sidecars"


class SidecarStore:
    """사이드카 폴더 관리자 — 영상 hash → 사이드카 파일 매핑."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ---- public API ----
    def load_for(self, video_path: Path) -> Sidecar | None:
        """영상에 매칭되는 사이드카 로드. 없으면 None.

        충돌 회피: hash 가 같아도 사이드카의 source_path 가 다르면 다른 파일.
        """
        video_path = Path(video_path)
        h = compute_video_hash(video_path)
        for candidate in self._candidates_for_hash(h):
            sc = load(candidate)
            if sc.source_path == str(video_path) or sc.source_path == "":
                return sc
        return None

    def save_for(self, video_path: Path, sc: Sidecar) -> Path:
        """사이드카 저장. 충돌 시 suffix 붙여 새 파일 생성. 저장된 절대경로 반환."""
        video_path = Path(video_path)
        h = sc.source_hash or compute_video_hash(video_path)
        sc.source_hash = h
        sc.source_path = str(video_path)
        target = self._select_target(h, video_path)
        save_atomic(target, sc)
        return target

    # ---- internal ----
    def _candidates_for_hash(self, h: str) -> list[Path]:
        """hash 로 시작하는 모든 사이드카 파일 (충돌 후보)."""
        if not self.root.exists():
            return []
        return sorted(self.root.glob(f"{h}*{SIDECAR_EXT}"))

    def _select_target(self, h: str, video_path: Path) -> Path:
        """저장할 파일 경로 선택. 같은 hash 의 기존 파일 중 같은 source_path 면 그것을,
        아니면 suffix(_2, _3, …) 붙여 새 파일.
        """
        for candidate in self._candidates_for_hash(h):
            try:
                existing = load(candidate)
            except Exception:
                continue
            if existing.source_path == str(video_path) or existing.source_path == "":
                return candidate
        # 새 파일 — suffix 결정
        existing_suffixes = {p.stem[len(h):] for p in self._candidates_for_hash(h)}
        if "" not in existing_suffixes:
            return self.root / f"{h}{SIDECAR_EXT}"
        i = 2
        while f"_{i}" in existing_suffixes:
            i += 1
        return self.root / f"{h}_{i}{SIDECAR_EXT}"
