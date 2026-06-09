from PySide6.QtGui import QImage
from screen_recorder.ui.library_model import LibraryModel, EntryKind
from screen_recorder.ui.docks.library_panel import LibraryPanel


def _img() -> QImage:
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


def test_panel_reflects_model_add(qtbot):
    m = LibraryModel()
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    assert p.list_widget.count() == 0
    m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    assert p.list_widget.count() == 1


def test_panel_reflects_model_remove(qtbot):
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    assert p.list_widget.count() == 1
    m.remove(e.id)
    assert p.list_widget.count() == 0


def test_clicking_item_emits_open(qtbot):
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.entry_open_requested, timeout=200) as blocker:
        p.list_widget.itemClicked.emit(p.list_widget.item(0))
    assert blocker.args == [e.id]


def test_document_item_drag_carries_file_url(qtbot, tmp_path):
    # 비교(DIFF) 뷰로 드래그하려면 항목 드래그 시 mimeData 에 파일 URL 이 실려야 한다.
    from pathlib import Path
    p = Path(tmp_path) / "doc.md"
    p.write_text("x", encoding="utf-8")
    m = LibraryModel()
    e = m.add(EntryKind.DOCUMENT, thumbnail=QImage(), source_label="d",
              display_name="doc", path=p)
    panel = LibraryPanel(m)
    qtbot.addWidget(panel)
    item = panel._items_by_id[e.id]
    mime = panel._mime_for_item(item)
    assert mime is not None and mime.hasUrls()
    assert mime.urls()[0].toLocalFile().endswith("doc.md")


def test_pathless_item_has_no_drag_mime(qtbot):
    # 경로 없는 항목(예: 미저장 캡처)은 드래그 mime 가 없어 드래그되지 않는다.
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    panel = LibraryPanel(m)
    qtbot.addWidget(panel)
    item = panel._items_by_id[e.id]
    assert panel._mime_for_item(item) is None


def _send_key(qtbot, widget, key, modifier=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    mods = modifier if modifier is not None else Qt.NoModifier
    ev = QKeyEvent(QEvent.KeyPress, key, mods)
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(widget, ev)


def test_del_emits_remove_not_delete(qtbot):
    """Del 단독: entry_remove_requested 발화 (라이브러리에서만 제외)."""
    from PySide6.QtCore import Qt
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    p.list_widget.setCurrentRow(0)
    with qtbot.assertNotEmitted(p.entry_delete_requested):
        with qtbot.waitSignal(p.entry_remove_requested, timeout=300) as blocker:
            _send_key(qtbot, p.list_widget, Qt.Key_Delete)
    assert blocker.args == [e.id]


def test_shift_del_emits_delete(qtbot):
    """Shift+Del: entry_delete_requested 발화 (휴지통)."""
    from PySide6.QtCore import Qt
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    p.list_widget.setCurrentRow(0)
    with qtbot.assertNotEmitted(p.entry_remove_requested):
        with qtbot.waitSignal(p.entry_delete_requested, timeout=300) as blocker:
            _send_key(qtbot, p.list_widget, Qt.Key_Delete, Qt.ShiftModifier)
    assert blocker.args == [e.id]


def test_document_item_text_flush_left_no_thumbnail_placeholder(qtbot):
    # 회귀: 문서(.md)는 썸네일이 없어 아이콘 칸(48px)이 빈다. _TwoLineDelegate 가 그
    # 빈 칸을 0폭으로 접어 텍스트를 왼쪽 끝(≈PADDING)에 붙여야 한다. 접지 않으면
    # 텍스트가 ~57px 밀린 빈 플레이스홀더가 생긴다(사용자 보고).
    from PySide6.QtGui import QColor
    m = LibraryModel()
    # 썸네일 있는 이미지(아이콘 칸 유지) + 썸네일 없는 문서(아이콘 칸 접힘) 대비.
    thumb = QImage(48, 32, QImage.Format_RGB32)
    thumb.fill(QColor("#c0392b"))
    img_e = m.add(EntryKind.SCREENSHOT, thumbnail=thumb, source_label="region",
                  display_name="shot.png")
    doc_e = m.add(EntryKind.DOCUMENT, thumbnail=QImage(), source_label="d",
                  display_name="문서.md")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    p.resize(240, 200)
    p.show()
    qtbot.waitExposed(p)

    def _content_left(item):
        rect = p.list_widget.visualItemRect(item)
        image = p.list_widget.viewport().grab().toImage()
        bg = image.pixelColor(rect.left() + 2, rect.top() + 2)
        for xx in range(max(rect.left(), 0), min(rect.right(), image.width() - 1)):
            for yy in range(max(rect.top(), 0), min(rect.bottom(), image.height() - 1)):
                c = image.pixelColor(xx, yy)
                if (abs(c.red()-bg.red()) + abs(c.green()-bg.green())
                        + abs(c.blue()-bg.blue())) > 50:
                    return xx - rect.left()
        return None

    doc_indent = _content_left(p._items_by_id[doc_e.id])
    img_indent = _content_left(p._items_by_id[img_e.id])
    # 문서 텍스트는 왼쪽 끝(< 20px). 빈 48px 플레이스홀더가 남아 있으면 ~57px.
    assert doc_indent is not None and doc_indent < 20, f"doc_indent={doc_indent}"
    # 이미지는 썸네일(아이콘)이 여전히 왼쪽 끝에 그려진다(회귀 아님 확인).
    assert img_indent is not None and img_indent < 20, f"img_indent={img_indent}"


def test_context_menu_separates_library_remove_and_trash(qtbot):
    """우클릭 메뉴: '라이브러리에서만 삭제' 와 '휴지통에 넣기' 가 별도 항목으로 분리되고
    각각 다른 시그널을 발화해야 한다 (사용자 보고: 두 문구가 헷갈림)."""
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    item = p._items_by_id[e.id]
    menu = p._build_context_menu(item, e.id)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "라이브러리에서만 삭제 (Del)" in texts
    assert "휴지통에 넣기 (Shift+Del)" in texts

    remove_a = next(a for a in menu.actions()
                    if a.text() == "라이브러리에서만 삭제 (Del)")
    trash_a = next(a for a in menu.actions()
                   if a.text() == "휴지통에 넣기 (Shift+Del)")
    # 라이브러리에서만 삭제 → remove 시그널만 (휴지통 시그널 발화 X).
    with qtbot.assertNotEmitted(p.entry_delete_requested):
        with qtbot.waitSignal(p.entry_remove_requested, timeout=300) as b:
            remove_a.trigger()
    assert b.args == [e.id]
    # 휴지통에 넣기 → delete 시그널만 (remove 시그널 발화 X).
    with qtbot.assertNotEmitted(p.entry_remove_requested):
        with qtbot.waitSignal(p.entry_delete_requested, timeout=300) as b2:
            trash_a.trigger()
    assert b2.args == [e.id]


def test_document_mode_shows_only_documents(qtbot):
    # 문서 모드에선 이미지/영상은 숨고 DOCUMENT 항목만 보여야 함 (문서 라이브러리 통합).
    from screen_recorder.ui.mode_controller import AppMode, ModeController
    m = LibraryModel()
    m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    m.add(EntryKind.VIDEO, thumbnail=_img(), source_label="rec")
    doc = m.add(EntryKind.DOCUMENT, thumbnail=_img(), source_label="opened",
                display_name="d.md")
    mc = ModeController(AppMode.IMAGE)
    p = LibraryPanel(m, mc)
    qtbot.addWidget(p)
    mc.set_mode(AppMode.DOCUMENT)
    visible = [p.list_widget.item(i) for i in range(p.list_widget.count())
               if not p.list_widget.item(i).isHidden()]
    assert len(visible) == 1
    assert not p._items_by_id[doc.id].isHidden()
    assert LibraryPanel._kind_for_mode(AppMode.DOCUMENT) is EntryKind.DOCUMENT
