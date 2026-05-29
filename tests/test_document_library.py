"""문서(DOCUMENT) 라이브러리 통합 — 모델/패널 단위 테스트."""


def test_entrykind_document_distinct():
    from screen_recorder.ui.library_model import EntryKind
    assert EntryKind.DOCUMENT.value == "document"
    assert EntryKind.DOCUMENT is not EntryKind.IMAGE
    assert EntryKind.DOCUMENT is not EntryKind.VIDEO


def test_add_with_id_keeps_id(qtbot):
    from PySide6.QtGui import QImage
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    m = LibraryModel()
    reserved = m.next_id()            # blank 문서가 탭에 쓰던 id
    e = m.add_with_id(reserved, EntryKind.DOCUMENT, thumbnail=QImage(),
                      source_label="saved", display_name="a.md")
    assert e.id == reserved
    assert m.get(reserved) is e
    assert m.entries(EntryKind.DOCUMENT) == [e]


def test_prefix_for_document_kind():
    from screen_recorder.ui.docks.library_panel import LibraryPanel
    from screen_recorder.ui.library_model import EntryKind
    # SCREENSHOT 은 IMAGE 의 별칭(값 동일) — VIDEO/DOCUMENT 를 먼저 걸러야 함.
    assert LibraryPanel._prefix_for_kind(EntryKind.DOCUMENT) == "📄"
    assert LibraryPanel._prefix_for_kind(EntryKind.VIDEO) == "🎞"
    assert LibraryPanel._prefix_for_kind(EntryKind.IMAGE) == "📸"


def test_kind_for_mode_document():
    from screen_recorder.ui.docks.library_panel import LibraryPanel
    from screen_recorder.ui.mode_controller import AppMode
    from screen_recorder.ui.library_model import EntryKind
    assert LibraryPanel._kind_for_mode(AppMode.DOCUMENT) is EntryKind.DOCUMENT


def test_document_entry_visible_only_in_document_mode(qtbot):
    from PySide6.QtGui import QImage
    from screen_recorder.ui.docks.library_panel import LibraryPanel
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    from screen_recorder.ui.mode_controller import ModeController, AppMode
    model = LibraryModel()
    mc = ModeController()
    panel = LibraryPanel(model, mc)
    qtbot.addWidget(panel)
    entry = model.add(EntryKind.DOCUMENT, thumbnail=QImage(),
                      source_label="opened", display_name="d.md")
    item = panel._items_by_id[entry.id]
    mc.set_mode(AppMode.DOCUMENT)
    assert not item.isHidden()
    mc.set_mode(AppMode.IMAGE)
    assert item.isHidden()       # 이미지 모드에선 문서 숨김
