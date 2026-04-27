from PySide6.QtGui import QImage
from screen_recorder.ui.library_model import LibraryEntry, LibraryModel, EntryKind


def _img() -> QImage:
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


def test_add_screenshot_entry_assigns_id():
    m = LibraryModel()
    entry = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    assert entry.id is not None
    assert entry.kind is EntryKind.SCREENSHOT
    assert entry.source_label == "region"
    assert m.entries() == [entry]


def test_add_video_entry_with_path_and_duration(tmp_path):
    m = LibraryModel()
    p = tmp_path / "rec.mp4"
    p.write_bytes(b"x")
    entry = m.add(EntryKind.VIDEO, thumbnail=_img(), source_label="fullscreen",
                  path=p, duration_ms=32000)
    assert entry.kind is EntryKind.VIDEO
    assert entry.path == p
    assert entry.duration_ms == 32000


def test_remove_entry_drops_from_list():
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    m.remove(e.id)
    assert m.entries() == []


def test_entries_are_in_reverse_chronological_order():
    m = LibraryModel()
    a = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    b = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="full")
    assert m.entries() == [b, a]


def test_entries_filtered_by_kind():
    m = LibraryModel()
    s = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    v = m.add(EntryKind.VIDEO, thumbnail=_img(), source_label="full",
              path=None, duration_ms=0)
    assert m.entries(kind=EntryKind.SCREENSHOT) == [s]
    assert m.entries(kind=EntryKind.VIDEO) == [v]


def test_signal_emitted_on_add(qtbot):
    m = LibraryModel()
    with qtbot.waitSignal(m.entry_added, timeout=200):
        m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")


def test_signal_emitted_on_remove(qtbot):
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    with qtbot.waitSignal(m.entry_removed, timeout=200):
        m.remove(e.id)
