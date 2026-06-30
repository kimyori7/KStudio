"""`_internal` 폴더 지문 + 코드패치 포함 판정 — 순수.

지문은 (정렬된 상대경로 + 파일 내용지문) 위에서 계산해 PyInstaller 산출물의 빌드별
타임스탬프/파일순서 흔들림에 불변하게 한다 → "같은 의존성 = 같은 해시".

⚠️ base_library.zip 함정: PyInstaller 는 base_library.zip 의 멤버를 빌드마다 다른
순서로 기록한다(멤버 이름·내용은 동일, 순서만 랜덤 — 실측 확인). 따라서 zip 은 raw
바이트로 해싱하면 안 되고, 멤버를 (정렬된 이름 + 멤버 content sha256)으로 정규화해
순서 불변하게 만든다. 안 그러면 의존성이 안 변해도 매 빌드 해시가 달라져 30MB
코드패치가 영영 선택되지 않는다(기능 무력화).
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

_CHUNK = 1 << 16


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_content_sha256(path: Path) -> str:
    """zip 의 (정렬된 멤버이름 + 멤버 content sha256) 정규화 해시 — 멤버 순서 불변."""
    h = hashlib.sha256()
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            h.update(name.encode("utf-8"))
            h.update(hashlib.sha256(zf.read(name)).digest())
    return h.hexdigest()


def _entry_digest(path: Path) -> str:
    """파일 1개의 내용 지문. zip 은 멤버 정규화(순서 불변), 그 외는 raw content."""
    if path.suffix.lower() == ".zip" and zipfile.is_zipfile(path):
        return _zip_content_sha256(path)
    return _file_sha256(path)


def compute_internal_hash(internal_dir: Path) -> str:
    """폴더 내 모든 파일의 (상대경로, 내용지문) 을 정렬·직렬화한 단일 sha256."""
    entries = []
    for p in sorted(internal_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(internal_dir).as_posix()   # OS 무관 구분자
            entries.append(f"{rel}:{_entry_digest(p)}")
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return digest


def decide_code_patch(new_hash: str, prev_hash: str | None) -> bool:
    """30MB 코드 패치를 추가 생성할지: 직전 해시가 있고 같을 때만 True."""
    return prev_hash is not None and new_hash == prev_hash
