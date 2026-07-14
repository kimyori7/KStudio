"""LibraryModel 순서 변경 — move_to_top / set_order (라이브러리 공통 개선, 2026-07-14).

- move_to_top: 파일을 열 때 그 항목을 라이브러리 맨 위로 (이미 있어도).
- set_order: 패널의 드래그앤드롭 재정렬 결과(위→아래 id 목록)를 모델에 반영.
"""
from PySide6.QtGui import QImage

from screen_recorder.ui.library_model import LibraryModel, EntryKind


def _img() -> QImage:
    img = QImage(4, 4, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


def _model_abc():
    """a → b → c 순서로 추가. entries() (위→아래) == [c, b, a]."""
    m = LibraryModel()
    a = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="a")
    b = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="b")
    c = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="c")
    return m, a, b, c


def _ids(model):
    return [e.id for e in model.entries()]


def test_move_to_top_moves_entry_to_front():
    m, a, b, c = _model_abc()
    assert m.move_to_top(a.id) is True
    assert _ids(m) == [a.id, c.id, b.id]


def test_move_to_top_emits_signals():
    m, a, b, c = _model_abc()
    moved, reordered = [], []
    m.entry_moved_to_top.connect(moved.append)
    m.entries_reordered.connect(lambda: reordered.append(True))
    m.move_to_top(a.id)
    assert moved == [a.id]
    assert reordered == [True]


def test_move_to_top_noop_when_already_top():
    m, a, b, c = _model_abc()
    moved, reordered = [], []
    m.entry_moved_to_top.connect(moved.append)
    m.entries_reordered.connect(lambda: reordered.append(True))
    assert m.move_to_top(c.id) is False       # c 가 이미 맨 위
    assert _ids(m) == [c.id, b.id, a.id]
    assert moved == [] and reordered == []    # 불필요한 저장 트리거 없음


def test_move_to_top_unknown_id_returns_false():
    m, a, b, c = _model_abc()
    assert m.move_to_top(9999) is False
    assert _ids(m) == [c.id, b.id, a.id]


def test_set_order_applies_top_to_bottom_order():
    m, a, b, c = _model_abc()
    reordered = []
    m.entries_reordered.connect(lambda: reordered.append(True))
    m.set_order([a.id, c.id, b.id])
    assert _ids(m) == [a.id, c.id, b.id]
    assert reordered == [True]


def test_set_order_ignores_unknown_ids_and_keeps_missing_entries():
    m, a, b, c = _model_abc()
    # 모르는 id 는 무시, 목록에서 빠진 항목(a)은 사라지지 않고 맨 아래에 유지.
    m.set_order([b.id, 9999, c.id])
    assert set(_ids(m)) == {a.id, b.id, c.id}
    assert _ids(m)[:2] == [b.id, c.id]
    assert _ids(m)[-1] == a.id
