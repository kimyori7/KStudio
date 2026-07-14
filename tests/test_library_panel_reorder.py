"""라이브러리 패널 재정렬 — 드래그앤드롭 행 이동 + move_to_top 행 동기화 (2026-07-14).

실제 QDrag 실행은 e2e 로만 가능하므로, 드롭 처리의 각 단계를 직접 검증한다:
- drop_row_for_pos: 드롭 좌표 → 삽입 행 계산
- move_row_to: 행 이동(같은 QListWidgetItem 인스턴스 유지) + 모델 순서 반영
- entry_moved_to_top: 모델이 항목을 맨 위로 올리면 패널 행도 따라 움직임
- drag_mime_for_item: 경로 없는 항목도 내부 재정렬용 marker mime 로 드래그 가능
"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage

from screen_recorder.ui.library_model import LibraryModel, EntryKind
from screen_recorder.ui.docks.library_panel import LibraryPanel


def _img() -> QImage:
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


def _panel_with_three(qtbot):
    """추가 순서 a→b→c. 시각 순서(위→아래): c, b, a."""
    m = LibraryModel()
    a = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="a")
    b = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="b")
    c = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="s", display_name="c")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    return m, p, (a, b, c)


def _row_ids(panel):
    lw = panel.list_widget
    return [int(lw.item(i).data(Qt.UserRole)) for i in range(lw.count())]


def test_model_move_to_top_moves_row_to_top(qtbot):
    m, p, (a, b, c) = _panel_with_three(qtbot)
    item_a = p._items_by_id[a.id]
    m.move_to_top(a.id)
    assert p.list_widget.count() == 3
    assert p.list_widget.item(0) is item_a          # 같은 인스턴스가 맨 위로
    assert _row_ids(p) == [a.id, c.id, b.id]


def test_move_row_to_updates_rows_and_model(qtbot):
    m, p, (a, b, c) = _panel_with_three(qtbot)
    lw = p.list_widget
    lw.setCurrentRow(2)                              # 맨 아래 a 선택(드래그 소스)
    item_a = p._items_by_id[a.id]
    assert lw.move_row_to(2, 0) is True              # a 를 맨 위로
    assert _row_ids(p) == [a.id, c.id, b.id]
    assert [e.id for e in m.entries()] == [a.id, c.id, b.id]   # 모델에도 반영
    assert p._items_by_id[a.id] is item_a            # 매핑 인스턴스 유지
    assert lw.currentItem() is item_a                # 선택 유지


def test_move_row_to_noop_for_same_position(qtbot):
    m, p, (a, b, c) = _panel_with_three(qtbot)
    lw = p.list_widget
    before = _row_ids(p)
    assert lw.move_row_to(1, 1) is False             # 제자리(자기 위)
    assert lw.move_row_to(1, 2) is False             # 제자리(자기 아래)
    assert _row_ids(p) == before


def test_drop_row_for_pos_geometry(qtbot):
    m, p, (a, b, c) = _panel_with_three(qtbot)
    p.resize(240, 300)
    p.show()
    qtbot.waitExposed(p)
    lw = p.list_widget
    r0 = lw.visualItemRect(lw.item(0))
    # 첫 항목 위쪽 절반 → 0, 아래쪽 절반 → 1.
    assert lw.drop_row_for_pos(QPoint(r0.center().x(), r0.top() + 1)) == 0
    assert lw.drop_row_for_pos(QPoint(r0.center().x(), r0.bottom() - 1)) == 1
    # 마지막 항목 아래 빈 공간 → 맨 끝(count).
    r2 = lw.visualItemRect(lw.item(2))
    assert lw.drop_row_for_pos(QPoint(r2.center().x(), r2.bottom() + 30)) == 3


def test_pathless_item_gets_internal_drag_mime(qtbot):
    from screen_recorder.ui.docks.library_list_widget import INTERNAL_MIME
    m, p, (a, b, c) = _panel_with_three(qtbot)
    item = p._items_by_id[a.id]                      # path 없음(미저장 캡처)
    mime = p.list_widget.drag_mime_for_item(item)
    assert mime is not None and mime.hasFormat(INTERNAL_MIME)
    assert not mime.hasUrls()                        # 외부 타깃엔 여전히 안 실림
    assert p._mime_for_item(item) is None            # 기존 계약 유지


def test_pathful_item_drag_mime_has_urls_and_marker(qtbot, tmp_path):
    from screen_recorder.ui.docks.library_list_widget import INTERNAL_MIME
    f = tmp_path / "doc.md"
    f.write_text("x", encoding="utf-8")
    m = LibraryModel()
    e = m.add(EntryKind.DOCUMENT, thumbnail=QImage(), source_label="d",
              display_name="doc.md", path=f)
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    mime = p.list_widget.drag_mime_for_item(p._items_by_id[e.id])
    assert mime.hasFormat(INTERNAL_MIME)
    assert mime.hasUrls() and mime.urls()[0].toLocalFile().endswith("doc.md")
