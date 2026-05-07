"""효과 베이스 dataclass 와 컬렉션."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable, Iterator
import uuid


def _new_id() -> str:
    """UUID4 (dashed hex, 36자)."""
    return str(uuid.uuid4())


@dataclass
class Effect:
    """모든 효과 종류의 공통 베이스.

    각 종류별 dataclass(Caption/Speed/Zoom/Broll/Cut) 가 이 클래스를 상속해
    추가 필드를 가진다. 시간 단위는 모두 ms (정수).
    """
    type: str
    in_ms: int
    out_ms: int
    id: str = field(default_factory=_new_id)

    def __post_init__(self) -> None:
        if self.in_ms < 0:
            raise ValueError(f"in_ms must be >= 0, got {self.in_ms}")
        if self.out_ms <= self.in_ms:
            raise ValueError(
                f"out_ms must be > in_ms (got in_ms={self.in_ms}, out_ms={self.out_ms})"
            )

    @property
    def duration_ms(self) -> int:
        return self.out_ms - self.in_ms


class EffectList:
    """Effect 컬렉션 — list wrapper + 정렬·필터 헬퍼."""

    def __init__(self, effects: Iterable[Effect] | None = None) -> None:
        self._items: list[Effect] = list(effects) if effects else []

    def append(self, effect: Effect) -> None:
        self._items.append(effect)

    def remove(self, effect_id: str) -> None:
        self._items = [e for e in self._items if e.id != effect_id]

    def find(self, effect_id: str) -> Effect | None:
        return next((e for e in self._items if e.id == effect_id), None)

    def sorted_by_time(self) -> list[Effect]:
        return sorted(self._items, key=lambda e: e.in_ms)

    def of_type(self, effect_type: str) -> list[Effect]:
        return [e for e in self._items if e.type == effect_type]

    def __iter__(self) -> Iterator[Effect]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
