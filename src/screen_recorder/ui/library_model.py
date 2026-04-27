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
    source_label: str          # "region" / "fullscreen" / "window"
    created_at: datetime = field(default_factory=datetime.now)
    path: Optional[Path] = None
    duration_ms: int = 0


class LibraryModel(QObject):
    entry_added = Signal(object)    # LibraryEntry
    entry_removed = Signal(int)     # entry id

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[LibraryEntry] = []
        self._id_seq = count(1)

    def add(self, kind: EntryKind, *, thumbnail: QImage, source_label: str,
            path: Optional[Path] = None, duration_ms: int = 0) -> LibraryEntry:
        entry = LibraryEntry(
            id=next(self._id_seq),
            kind=kind,
            thumbnail=thumbnail,
            source_label=source_label,
            path=path,
            duration_ms=duration_ms,
        )
        self._entries.append(entry)
        self.entry_added.emit(entry)
        return entry

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
