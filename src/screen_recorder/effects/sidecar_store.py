"""영상 hash 계산 + 사이드카 폴더 관리.

사이드카는 KStudio 전용 폴더(예: %APPDATA%\\KStudio\\sidecars\\) 또는 사용자가 환경
설정에서 지정한 폴더에 저장된다.

파일명 형식 (Phase 19.5 hotfix3): `<영상_basename>_<hash>.kstudio`
- basename: 영상 파일의 stem (확장자 제외, 안전 문자만)
- hash: 영상 파일 첫 1MB 의 sha-1 hex (40자)

이미지 편집기도 `.kstudio` (zip) 를 쓰지만 사이드카 폴더와는 분리되며, 파일 열기 시
magic 검사 (첫 바이트 `PK` = zip, `{` = JSON) 로 분기.

구 형식 (`<hash>.kstudio`) 은 load 호환 유지 + 다음 save 시 새 형식으로 자동
마이그레이션 (구 파일 삭제).

같은 hash + 같은 basename + 다른 source_path 충돌 시 `<basename>_<hash>_2.kstudio` 식의
suffix 추가.
"""
from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path

from .sidecar import Sidecar, save_atomic, load


HASH_PREFIX_BYTES = 1 * 1024 * 1024     # 첫 1MB
SIDECAR_EXT = ".kstudio"


def _safe_filename(stem: str) -> str:
    """파일명에 안전한 문자만 — Windows 금지 문자(<>:"/\\|?*) 와 제어문자 제거."""
    bad = set('<>:"/\\|?*')
    out = []
    for c in stem:
        if c in bad or ord(c) < 32:
            out.append("_")
        else:
            out.append(c)
    cleaned = "".join(out).strip().rstrip(".")
    return cleaned or "video"


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
        """사이드카 저장. 새 형식 (`<basename>_<hash>.kvedit`) 으로 쓰고 구 형식 파일
        있으면 자동 삭제 (마이그레이션). 저장된 절대경로 반환.
        """
        video_path = Path(video_path)
        h = sc.source_hash or compute_video_hash(video_path)
        sc.source_hash = h
        sc.source_path = str(video_path)
        target = self._select_target(h, video_path)
        save_atomic(target, sc)
        # 구 형식 파일 (`<hash>.kstudio` 등) 이 target 과 다르면 삭제 — 자동 마이그레이션.
        # 동일 source_path 의 다른 후보들 정리.
        for candidate in self._candidates_for_hash(h):
            if candidate == target:
                continue
            try:
                existing = load(candidate)
            except Exception:
                continue
            if existing.source_path == str(video_path):
                try:
                    candidate.unlink()
                except OSError:
                    pass
        return target

    # ---- internal ----
    def _candidates_for_hash(self, h: str) -> list[Path]:
        """hash 가 stem 어딘가에 있는 모든 사이드카 파일.

        Phase 19.5 사용자 보고 (재시작 후 자동 로드 안 됨) — 이전 glob 패턴
        (`*_<hash>.kstudio` 등) 이 Windows 에서 매칭 실패하는 케이스가 있어 단순
        iterdir + 문자열 검사로 교체. hash 가 40자 SHA1 hex 라 충돌 가능성 거의 없음.
        신규 (`<basename>_<hash>...`) + 구 (`<hash>...`) 형식 모두 자연스럽게 매칭.
        """
        if not self.root.exists() or not h:
            return []
        candidates: list[Path] = []
        for p in self.root.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() != SIDECAR_EXT:
                continue
            if h in p.stem:
                candidates.append(p)
        return sorted(candidates)

    def _select_target(self, h: str, video_path: Path) -> Path:
        """저장 경로 — 항상 새 형식 `<basename>_<hash>.kvedit`. 충돌 시 _<n> suffix.

        같은 basename + 같은 hash 파일이 이미 있고 source_path 가 같으면 그 파일에 덮어쓰기.
        다른 source_path 의 hash 충돌 (드물지만) 이면 `_2`, `_3` ... 추가.
        """
        basename = _safe_filename(video_path.stem)
        base_path = self.root / f"{basename}_{h}{SIDECAR_EXT}"
        if base_path.exists():
            try:
                existing = load(base_path)
                if existing.source_path == str(video_path) or existing.source_path == "":
                    return base_path
            except Exception:
                # 손상된 파일 — 덮어쓰기.
                return base_path
            # 다른 source_path 의 충돌 — suffix 찾기.
            i = 2
            while True:
                candidate = self.root / f"{basename}_{h}_{i}{SIDECAR_EXT}"
                if not candidate.exists():
                    return candidate
                try:
                    existing = load(candidate)
                    if existing.source_path == str(video_path):
                        return candidate
                except Exception:
                    return candidate
                i += 1
        return base_path
