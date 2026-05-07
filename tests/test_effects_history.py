"""Undo/Redo 스택 — Sidecar 전체 snapshot."""
import pytest

from screen_recorder.effects.history import History
from screen_recorder.effects.sidecar import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect


def _sc_with_n(n: int) -> Sidecar:
    return Sidecar(
        source_path="x",
        source_hash="h",
        trim=Trim(in_ms=0, out_ms=10000),
        effects=[CaptionEffect(in_ms=i * 100, out_ms=i * 100 + 50, text=f"c{i}")
                 for i in range(n)],
    )


def test_initial_state_no_undo():
    h = History(initial=_sc_with_n(0))
    assert h.can_undo() is False
    assert h.can_redo() is False


def test_push_then_undo_restores_previous():
    h = History(initial=_sc_with_n(0))
    h.push(_sc_with_n(1))
    h.push(_sc_with_n(2))
    assert h.can_undo() is True
    sc = h.undo()
    assert len(sc.effects) == 1
    sc = h.undo()
    assert len(sc.effects) == 0
    assert h.can_undo() is False


def test_redo_after_undo():
    h = History(initial=_sc_with_n(0))
    h.push(_sc_with_n(2))
    h.undo()
    assert h.can_redo() is True
    sc = h.redo()
    assert len(sc.effects) == 2
    assert h.can_redo() is False


def test_new_push_clears_redo_stack():
    h = History(initial=_sc_with_n(0))
    h.push(_sc_with_n(2))
    h.undo()
    h.push(_sc_with_n(3))   # 새 액션 → redo 사라짐
    assert h.can_redo() is False


def test_limit_drops_oldest():
    h = History(initial=_sc_with_n(0), limit=3)
    for i in range(1, 6):  # 5개 push
        h.push(_sc_with_n(i))
    # 현재 + undo 가능 = 3 (limit). 가장 오래된 게 사라짐.
    sc = h.current()
    assert len(sc.effects) == 5
    h.undo()    # → 4
    h.undo()    # → 3
    assert len(h.current().effects) == 3
    assert h.can_undo() is False


def test_undo_when_empty_raises():
    h = History(initial=_sc_with_n(0))
    with pytest.raises(IndexError):
        h.undo()


def test_redo_when_empty_raises():
    h = History(initial=_sc_with_n(0))
    with pytest.raises(IndexError):
        h.redo()


def test_snapshot_isolation():
    """undo 로 받은 사이드카를 수정해도 history 안의 snapshot 은 영향 없음."""
    h = History(initial=_sc_with_n(0))
    h.push(_sc_with_n(2))
    sc = h.undo()
    sc.effects.append(CaptionEffect(in_ms=99999, out_ms=99999 + 50, text="hack"))
    sc2 = h.redo()
    # redo 결과는 깨끗한 2개여야 함
    assert len(sc2.effects) == 2
