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
    SCREENSHOT = "screenshot"
    VIDEO = "video"


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


class LibraryModel(QObject):
    entry_added = Signal(object)    # LibraryEntry
    entry_removed = Signal(int)     # entry id
    entry_renamed = Signal(int, str)   # (entry_id, new_display_name) — 모델이 갱신된 후 emit

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[LibraryEntry] = []
        self._id_seq = count(1)

    def add(self, kind: EntryKind, *, thumbnail: QImage, source_label: str,
            display_name: str = "", path: Optional[Path] = None,
            duration_ms: int = 0) -> LibraryEntry:
        entry = LibraryEntry(
            id=next(self._id_seq),
            kind=kind,
            thumbnail=thumbnail,
            source_label=source_label,
            display_name=display_name,
            path=path,
            duration_ms=duration_ms,
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
