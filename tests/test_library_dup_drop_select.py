"""라이브러리에 파일을 드롭하면 그 파일로 데려간다 — 모드 전환 + 라이브러리 선택.

사용자 요청(2026-06-02): "각 라이브러리에 파일 넣었을때 이미 중복인 파일을 넣으면 그
파일이 선택되게 해줘." → 후속: "영상 모드에서 이미지를 떨어뜨려도 중복이든 아니든 이미지
모드로 가는게 맞고, 중복이든 아니든 라이브러리에서 포커스 되어야지."

즉 라이브러리에 떨어뜨린 그 파일이 — 새 파일이든 중복이든 — (1) 그 종류에 맞는 모드로
전환되고 (2) 라이브러리 패널에서 선택(하이라이트)되어야 한다.

WebEngine teardown 세그폴트(기존 이슈)를 피하려고 문서 경로는 MarkdownTab 을 만들지 않는
_register_dropped_document 만 직접 호출하고, 문서 모드로 전환하지 않는다(선택 검증은
숨겨진 항목에도 동작하는 currentItem/_items_by_id 로 한다).
"""
from pathlib import Path

from PySide6.QtGui import QImage


def _save_png(path: Path, argb: int) -> Path:
    img = QImage(16, 16, QImage.Format_ARGB32)
    img.fill(argb)
    img.save(str(path), "PNG")
    return path


def _open_image(win, path: Path, argb: int):
    _save_png(path, argb)
    win._open_image_path(path)
    return path, win.tab_area.current_entry_id()


def test_mode_for_kind_maps_each_kind():
    """종류 → 모드 매핑 (SCREENSHOT 은 IMAGE 별칭)."""
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.ui.library_model import EntryKind
    from screen_recorder.ui.mode_controller import AppMode
    assert MainWindow._mode_for_kind(EntryKind.VIDEO) is AppMode.VIDEO
    assert MainWindow._mode_for_kind(EntryKind.DOCUMENT) is AppMode.DOCUMENT
    assert MainWindow._mode_for_kind(EntryKind.IMAGE) is AppMode.IMAGE
    assert MainWindow._mode_for_kind(EntryKind.SCREENSHOT) is AppMode.IMAGE


def test_drop_new_image_in_video_mode_switches_and_focuses(qtbot, tmp_path):
    """영상 모드에서 새 이미지를 드롭 → 이미지 모드로 전환 + 그 항목 선택."""
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    win.mode_controller.set_mode(AppMode.VIDEO)
    p = _save_png(tmp_path / "shot.png", 0xFF3344AA)
    win._on_library_files_dropped([str(p)])
    assert win.mode_controller.mode() is AppMode.IMAGE
    entry = win._find_library_entry_for_path(p)
    assert entry is not None
    panel = win.library_panel
    assert panel.list_widget.currentItem() is panel._items_by_id[entry.id]
    win.close()


def test_drop_duplicate_image_in_video_mode_switches_and_focuses(qtbot, tmp_path):
    """영상 모드에서 '이미 라이브러리에 있는' 이미지를 드롭 → 이미지 모드로 전환 + 선택."""
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.mode_controller import AppMode
    win = build_main_window()
    qtbot.addWidget(win)
    pa, eid_a = _open_image(win, tmp_path / "a.png", 0xFF111111)   # 라이브러리에 등록됨
    win.mode_controller.set_mode(AppMode.VIDEO)                    # 다른 모드로 이동
    win._on_library_files_dropped([str(pa)])                      # a 의 중복 드롭
    assert win.mode_controller.mode() is AppMode.IMAGE            # 이미지 모드로 복귀
    panel = win.library_panel
    assert panel.list_widget.currentItem() is panel._items_by_id[eid_a]
    win.close()


def test_register_dropped_document_focuses_new_and_duplicate(qtbot, tmp_path):
    """문서 .md 등록: 새 항목도, 중복 항목도 라이브러리에서 선택된다(중복 추가 없음)."""
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.library_model import EntryKind
    win = build_main_window()
    qtbot.addWidget(win)
    md = tmp_path / "doc.md"
    md.write_text("# hi", encoding="utf-8")
    panel = win.library_panel
    win._register_dropped_document(md)            # 새 문서 → 등록 + 선택
    entry = win._find_library_entry_for_path(md)
    assert entry is not None
    assert panel.list_widget.currentItem() is panel._items_by_id[entry.id]
    win._register_dropped_document(md)            # 중복 → 같은 항목 계속 선택, 추가 X
    assert len(win.library_model.entries(EntryKind.DOCUMENT)) == 1
    assert win._find_library_entry_for_path(md).id == entry.id
    assert panel.list_widget.currentItem() is panel._items_by_id[entry.id]
    win.close()
