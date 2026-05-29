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
