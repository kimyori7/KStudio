"""외부 파일 삭제 → 라이브러리/탭 취소선 + 오른쪽 ✕ 정리 (Phase 60).

아래에서 위로(레이어별) 검증:
  L1 모델: set_missing 가 값 변경 시에만 entry_missing_changed emit
  L2 탭: set_entry_deleted 가 위젯 표시 + _is_tab_index_deleted 토글, paint 무크래시
  L3 라이브러리: missing 역할 토글 + ✕ 히트테스트가 entry_remove_requested 발화
"""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QImage, QMouseEvent


def _img() -> QImage:
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


# ---------------- L1: 모델 ----------------
def test_set_missing_emits_only_on_change(qtbot):
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    seen = []
    m.entry_missing_changed.connect(lambda eid, mi: seen.append((eid, mi)))
    m.set_missing(e.id, True)
    m.set_missing(e.id, True)        # 값 동일 → 재발화 없음
    assert e.missing is True
    assert seen == [(e.id, True)]
    m.set_missing(e.id, False)
    assert e.missing is False
    assert seen == [(e.id, True), (e.id, False)]


# ---------------- L2: 탭 ----------------
def _make_tab_area(qtbot):
    from screen_recorder.ui.tab_area import TabArea
    from screen_recorder.ui.mode_controller import ModeController
    from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
    ta = TabArea(ModeController(), player_settings=PlayerSettings(),
                 player_hotkeys=PlayerHotkeys())
    qtbot.addWidget(ta)
    return ta


def test_tab_strikethrough_mark_and_clear(qtbot):
    ta = _make_tab_area(qtbot)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=7)
    idx = ta.find_index_by_entry(7)
    assert idx >= 0
    assert not ta._is_tab_index_deleted(idx)
    ta.set_entry_deleted(7, True)
    assert ta._is_tab_index_deleted(idx)
    ta.set_entry_deleted(7, False)
    assert not ta._is_tab_index_deleted(idx)


def test_deleted_tab_paint_does_not_crash(qtbot):
    ta = _make_tab_area(qtbot)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=8)
    ta.set_entry_deleted(8, True)
    ta.show()
    ta.tabBar().grab()      # 취소선 오버레이 paintEvent 강제 — 크래시 없어야


def test_close_discards_deleted_mark(qtbot):
    ta = _make_tab_area(qtbot)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=9)
    ta.set_entry_deleted(9, True)
    idx = ta.find_index_by_entry(9)
    ta._on_close_requested(idx)
    assert not ta._deleted_widgets       # 닫으면 삭제 표시 집합에서 빠짐


# ---------------- L3: 라이브러리 패널 ----------------
def test_panel_marks_missing_role(qtbot):
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    from screen_recorder.ui.docks.library_panel import LibraryPanel, _ROLE_MISSING
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    item = p._items_by_id[e.id]
    assert not item.data(_ROLE_MISSING)
    m.set_missing(e.id, True)
    assert item.data(_ROLE_MISSING) is True


def test_x_click_on_missing_emits_remove(qtbot):
    """advisor #5: 실제 ✕ 좌표를 계산해 클릭 → entry_remove_requested 발화(좌표공간 일치)."""
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    from screen_recorder.ui.docks.library_panel import LibraryPanel, _x_button_rect
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region",
              display_name="gone.png")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    p.resize(320, 200)
    p.show()
    qtbot.waitExposed(p)
    m.set_missing(e.id, True)
    item = p._items_by_id[e.id]
    rect = p.list_widget.visualItemRect(item)
    assert rect.width() > 0
    center = _x_button_rect(rect).center()
    got = []
    p.entry_remove_requested.connect(lambda eid: got.append(eid))
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(center), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    p.list_widget.mousePressEvent(ev)
    assert got == [e.id]


def test_click_left_of_x_does_not_remove(qtbot):
    """같은 행이라도 ✕ 밖(왼쪽 본문) 클릭은 제거 안 함 — 기존 열기/선택 경로 보존."""
    from screen_recorder.ui.library_model import LibraryModel, EntryKind
    from screen_recorder.ui.docks.library_panel import LibraryPanel
    m = LibraryModel()
    e = m.add(EntryKind.SCREENSHOT, thumbnail=_img(), source_label="region",
              display_name="gone.png")
    p = LibraryPanel(m)
    qtbot.addWidget(p)
    p.resize(320, 200)
    p.show()
    qtbot.waitExposed(p)
    m.set_missing(e.id, True)
    item = p._items_by_id[e.id]
    rect = p.list_widget.visualItemRect(item)
    got = []
    p.entry_remove_requested.connect(lambda eid: got.append(eid))
    left_point = QPointF(rect.left() + 6, rect.center().y())
    ev = QMouseEvent(QEvent.MouseButtonPress, left_point, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    p.list_widget.mousePressEvent(ev)
    assert got == []


# ---------------- L5: 통합 (MainWindow 전체 배선) ----------------
# 이미지(EditTab)로 검증 — 중앙 watcher/배선은 종류 무관(문서 탭도 동일 경로). 문서는
# WebEngine teardown 세그폴트(기존 이슈)를 유발하므로 통합 테스트에선 피한다.
def _open_image(win, tmp_path: Path):
    img = QImage(16, 16, QImage.Format_ARGB32)
    img.fill(0xFF334455)
    p = tmp_path / "pic.png"
    img.save(str(p), "PNG")
    win._open_image_path(p)
    return p, win.tab_area.current_entry_id()


def test_external_delete_marks_library_and_tab(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.docks.library_panel import _ROLE_MISSING
    win = build_main_window()
    qtbot.addWidget(win)
    p, eid = _open_image(win, tmp_path)
    assert eid is not None
    p.unlink()                       # 외부 삭제
    win._recheck_library_files()
    assert win.library_model.get(eid).missing is True
    assert win.library_panel._items_by_id[eid].data(_ROLE_MISSING) is True
    idx = win.tab_area.find_index_by_entry(eid)
    assert win.tab_area._is_tab_index_deleted(idx)
    win.close()


def test_x_remove_closes_tab_and_removes_entry(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p, eid = _open_image(win, tmp_path)
    p.unlink()
    win._recheck_library_files()
    assert win.library_model.get(eid).missing is True
    # ✕ 클릭과 동일 경로 — 패널이 entry_remove_requested 발화
    win.library_panel.entry_remove_requested.emit(eid)
    assert win.library_model.get(eid) is None              # 라이브러리에서 제거됨
    assert win.tab_area.find_index_by_entry(eid) < 0       # 열린 탭도 닫힘
    win.close()


def test_recreate_clears_missing(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p, eid = _open_image(win, tmp_path)
    p.unlink()
    win._recheck_library_files()
    assert win.library_model.get(eid).missing is True
    img = QImage(16, 16, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    img.save(str(p), "PNG")                                # 재생성
    win._recheck_library_files()
    assert win.library_model.get(eid).missing is False
    idx = win.tab_area.find_index_by_entry(eid)
    assert not win.tab_area._is_tab_index_deleted(idx)
    win.close()


def test_real_watcher_signal_marks_missing(qtbot, tmp_path):
    """실 OS 경로 검증: 진짜 파일 삭제 → directoryChanged → 디바운스 타이머 → 취소선.

    통합 테스트들은 _recheck_library_files 를 직접 부른다. 이 테스트는 수동 호출 없이
    실제 QFileSystemWatcher 시그널이 마킹까지 도달하는지(사용자가 보고한 그 경로) 확인한다.
    """
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    p, eid = _open_image(win, tmp_path)
    win._lib_recheck_timer.setInterval(50)     # 테스트 가속(기본 200ms)
    p.unlink()                                  # _recheck 직접 호출 없음 — OS 이벤트만
    qtbot.waitUntil(lambda: bool(win.library_model.get(eid).missing), timeout=5000)
    assert win.tab_area._is_tab_index_deleted(win.tab_area.find_index_by_entry(eid))
    win.close()
