"""세션 라이브러리 모델 — 이번 실행 동안의 결과물(스크린샷·영상) 보관."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from itertools import count
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


class EntryKind(Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"   # Markdown 문서 (문서 모드 라이브러리)
    AUDIO = "audio"         # mp3/오디오 — 전용 오디오 탭(자르기). 영상과 같은 모드 영역.
    # 하위 호환: 코드 베이스 안에서 "screenshot" 문자열로 비교하는 경우가 있을 수 있음.
    # 의미 동일이므로 새로 SCREENSHOT 별칭 유지 (값은 동일).
    SCREENSHOT = "image"


@dataclass
class LibraryEntry:
    id: int
    kind: EntryKind
    thumbnail: QImage
    source_label: str          # "region" / "fullscreen" / "window" (파일명 규칙 {target} 토큰용)
    display_name: str = ""     # 라이브러리/디스크에 보일 파일명 (예: "screenshot_2026-04-27_15-30.png")
    created_at: datetime = field(default_factory=datetime.now)
    path: Optional[Path] = None
    duration_ms: int = 0
    origin: str = "captured"   # "captured" | "opened"
    filmstrip: list = field(default_factory=list)   # list[QImage] — 트림 레인 배경 캐시
    missing: bool = False      # 디스크 파일이 외부에서 삭제됨 → 취소선 + X 정리 (Phase 60)


class LibraryModel(QObject):
    entry_added = Signal(object)    # LibraryEntry
    entry_removed = Signal(int)     # entry id
    entry_renamed = Signal(int, str)   # (entry_id, new_display_name) — 모델이 갱신된 후 emit
    entry_missing_changed = Signal(int, bool)  # (entry_id, missing) — 외부 삭제/복구 감지

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[LibraryEntry] = []
        self._id_seq = count(1)

    def add(self, kind: EntryKind, *, thumbnail: QImage, source_label: str,
            display_name: str = "", path: Optional[Path] = None,
            duration_ms: int = 0, origin: str = "captured") -> LibraryEntry:
        entry = LibraryEntry(
            id=next(self._id_seq),
            kind=kind,
            thumbnail=thumbnail,
            source_label=source_label,
            display_name=display_name,
            path=path,
            duration_ms=duration_ms,
            origin=origin,
        )
        self._entries.append(entry)
        self.entry_added.emit(entry)
        return entry

    def add_with_id(self, entry_id: int, kind: EntryKind, *, thumbnail: QImage,
                    source_label: str, display_name: str = "",
                    path: Optional[Path] = None, duration_ms: int = 0,
                    origin: str = "captured") -> LibraryEntry:
        """이미 next_id() 로 예약한 고유 id 로 entry 등록.

        blank(미저장) 문서가 라이브러리 없이 next_id 만으로 탭에 떠 있다가 저장되면,
        그 탭의 기존 id 를 유지한 채 라이브러리에 승격시킬 때 사용 (id 재발급 시
        탭↔entry 매핑이 깨짐 방지)."""
        entry = LibraryEntry(
            id=entry_id, kind=kind, thumbnail=thumbnail, source_label=source_label,
            display_name=display_name, path=path, duration_ms=duration_ms, origin=origin,
        )
        self._entries.append(entry)
        self.entry_added.emit(entry)
        return entry

    def rename(self, entry_id: int, new_name: str) -> None:
        """display_name 변경 (디스크 path rename 은 호출자 책임)."""
        for e in self._entries:
            if e.id == entry_id:
                e.display_name = new_name
                self.entry_renamed.emit(entry_id, new_name)
                return

    def set_missing(self, entry_id: int, missing: bool) -> None:
        """디스크 파일 삭제/복구 상태 토글. 값이 바뀔 때만 entry_missing_changed emit."""
        for e in self._entries:
            if e.id == entry_id:
                if e.missing != missing:
                    e.missing = missing
                    self.entry_missing_changed.emit(entry_id, missing)
                return

    def remove(self, entry_id: int) -> None:
        for i, e in enumerate(self._entries):
            if e.id == entry_id:
                del self._entries[i]
                self.entry_removed.emit(entry_id)
                return

    def entries(self, kind: Optional[EntryKind] = None) -> list[LibraryEntry]:
        items = list(reversed(self._entries))
        if kind is None:
            return items
        return [e for e in items if e.kind is kind]

    def next_id(self) -> int:
        """라이브러리 항목을 만들지 않고 고유 id 만 발급 (예: 문서 탭 — Phase 1 에선
        문서가 라이브러리에 들어가지 않지만 탭 추적용 고유 id 가 필요)."""
        return next(self._id_seq)

    def get(self, entry_id: int) -> Optional[LibraryEntry]:
        for e in self._entries:
            if e.id == entry_id:
                return e
        return None

    def clear(self) -> None:
        ids = [e.id for e in self._entries]
        self._entries.clear()
        for i in ids:
            self.entry_removed.emit(i)
