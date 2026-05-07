"""Undo/Redo 스택 — Sidecar 전체 snapshot."""
from __future__ import annotations
import copy
from collections import deque

from .sidecar import Sidecar


DEFAULT_LIMIT = 50


class History:
    """한 영상 탭의 Undo/Redo 스택.

    스냅샷 기반 — 한 step = Sidecar 전체의 deep copy. 단순·정확.
    limit 초과 시 가장 오래된 snapshot 폐기. 새 push 는 redo stack 초기화.
    """

    def __init__(self, initial: Sidecar, limit: int = DEFAULT_LIMIT) -> None:
        # limit = total states kept (current + undo stack), so undo holds limit-1
        self._undo: deque[Sidecar] = deque(maxlen=limit - 1)
        self._redo: deque[Sidecar] = deque()
        self._current: Sidecar = copy.deepcopy(initial)
        self._limit = limit

    # ---- query ----
    def can_undo(self) -> bool:
        return len(self._undo) > 0

    def can_redo(self) -> bool:
        return len(self._redo) > 0

    def current(self) -> Sidecar:
        return copy.deepcopy(self._current)

    # ---- mutation ----
    def push(self, new_state: Sidecar) -> None:
        """현재 상태를 undo 에 밀어넣고, new_state 를 현재로. redo stack 초기화."""
        self._undo.append(self._current)
        self._current = copy.deepcopy(new_state)
        self._redo.clear()

    def undo(self) -> Sidecar:
        """이전 상태 복원. 없으면 IndexError."""
        if not self._undo:
            raise IndexError("undo stack empty")
        self._redo.appendleft(self._current)
        self._current = self._undo.pop()
        return copy.deepcopy(self._current)

    def redo(self) -> Sidecar:
        """방금 undo 를 되돌림. 없으면 IndexError."""
        if not self._redo:
            raise IndexError("redo stack empty")
        self._undo.append(self._current)
        self._current = self._redo.popleft()
        return copy.deepcopy(self._current)
