"""캔버스 붙여넣기 (Phase 61) — AddLayerCommand / EditTab.paste_image / 클립보드 mime 파싱."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QSize, QUrl
from PySide6.QtGui import QColor, QImage, QUndoStack


def _solid(w: int, h: int, c: int) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor.fromRgba(c))
    return img


# --- AddLayerCommand ---------------------------------------------------------

def test_add_layer_command_redo_adds_and_activates():
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.add_layer import AddLayerCommand

    stack = LayerStack(QSize(50, 50))
    bg = ImageLayer(id=stack.next_id(), name="bg", pixmap=_solid(50, 50, 0xFFFFFFFF))
    stack.add_layer(bg)
    stack.set_active_layer(bg.id)

    new = ImageLayer(id=stack.next_id(), name="붙여넣기", pixmap=_solid(20, 20, 0xFFFF0000))
    undo = QUndoStack()
    undo.push(AddLayerCommand(stack, new))

    assert new in stack.layers
    assert stack.active_layer_id == new.id


def test_add_layer_command_undo_removes_and_restores_active():
    from image_editor.layer_model import LayerStack
    from image_editor.layers.image_layer import ImageLayer
    from image_editor.operations.add_layer import AddLayerCommand

    stack = LayerStack(QSize(50, 50))
    bg = ImageLayer(id=stack.next_id(), name="bg", pixmap=_solid(50, 50, 0xFFFFFFFF))
    stack.add_layer(bg)
    stack.set_active_layer(bg.id)

    new = ImageLayer(id=stack.next_id(), name="붙여넣기", pixmap=_solid(20, 20, 0xFFFF0000))
    undo = QUndoStack()
    undo.push(AddLayerCommand(stack, new))
    undo.undo()

    assert new not in stack.layers
    assert stack.active_layer_id == bg.id


# --- EditTab.paste_image -----------------------------------------------------

def test_paste_image_adds_layer_at_origin(qtbot):
    from screen_recorder.ui.edit_tab import EditTab
    from image_editor.layers.image_layer import ImageLayer

    tab = EditTab.from_blank(QSize(40, 30))
    before = len(tab.stack.layers)

    tab.paste_image(_solid(20, 20, 0xFFFF0000))

    assert len(tab.stack.layers) == before + 1
    active = tab.stack.active_layer()
    assert isinstance(active, ImageLayer)
    assert active.offset == QPoint(0, 0)
    assert active.pixmap.size() == QSize(20, 20)


def test_paste_image_normalizes_dpr(qtbot):
    from screen_recorder.ui.edit_tab import EditTab

    hidpi = _solid(20, 20, 0xFF00FF00)
    hidpi.setDevicePixelRatio(2.0)

    tab = EditTab.from_blank(QSize(40, 30))
    tab.paste_image(hidpi)

    assert tab.stack.active_layer().pixmap.devicePixelRatio() == 1.0


def test_paste_image_undo_removes_pasted_layer(qtbot):
    from screen_recorder.ui.edit_tab import EditTab

    tab = EditTab.from_blank(QSize(40, 30))
    before = len(tab.stack.layers)
    bg_id = tab.stack.active_layer_id

    tab.paste_image(_solid(20, 20, 0xFFFF0000))
    tab.undo_stack.undo()

    assert len(tab.stack.layers) == before
    assert tab.stack.active_layer_id == bg_id


def test_paste_image_null_is_noop(qtbot):
    from screen_recorder.ui.edit_tab import EditTab

    tab = EditTab.from_blank(QSize(40, 30))
    before = len(tab.stack.layers)

    tab.paste_image(QImage())

    assert len(tab.stack.layers) == before


# --- 클립보드 mime → QImage --------------------------------------------------

def test_image_from_clipboard_prefers_image_data():
    from screen_recorder.ui.clipboard_image import image_from_clipboard

    mime = QMimeData()
    mime.setImageData(_solid(12, 8, 0xFF112233))

    out = image_from_clipboard(mime)
    assert not out.isNull()
    assert out.size() == QSize(12, 8)


def test_image_from_clipboard_falls_back_to_file_url(tmp_path):
    from screen_recorder.ui.clipboard_image import image_from_clipboard

    png = tmp_path / "copied.png"
    assert _solid(16, 9, 0xFF445566).save(str(png), "PNG")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(png))])

    out = image_from_clipboard(mime)
    assert not out.isNull()
    assert out.size() == QSize(16, 9)


def test_image_from_clipboard_empty_returns_null():
    from screen_recorder.ui.clipboard_image import image_from_clipboard

    assert image_from_clipboard(QMimeData()).isNull()


def test_image_from_clipboard_non_image_url_returns_null(tmp_path):
    from screen_recorder.ui.clipboard_image import image_from_clipboard

    txt = tmp_path / "note.txt"
    txt.write_text("not an image", encoding="utf-8")

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(txt))])

    assert image_from_clipboard(mime).isNull()


# --- MainWindow 배선 ---------------------------------------------------------

def _win(qtbot, tmp_path):
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.core.settings import AppSettings
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_ctrl_v_registered_in_clipboard_shortcuts(qtbot, tmp_path):
    win = _win(qtbot, tmp_path)
    seqs = [sc.key().toString() for sc in win._image_clipboard_shortcuts]
    assert "Ctrl+V" in seqs
    win.close()


def test_paste_handler_adds_layer_from_clipboard(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    win = _win(qtbot, tmp_path)
    win._on_screenshot_captured(_solid(40, 30, 0xFF222222), "region")
    tab = win._current_screenshot_tab()
    assert tab is not None
    before = len(tab.stack.layers)

    mime = QMimeData()
    mime.setImageData(_solid(20, 20, 0xFFFF0000))
    QApplication.clipboard().setMimeData(mime)

    win._paste_to_current_screenshot()

    assert len(tab.stack.layers) == before + 1
    win.close()


def test_user_flow_copy_then_new_tab_then_paste(qtbot, tmp_path):
    """사용자 보고 흐름 그대로: 선택→진짜 복사→새 캔버스 탭(현재 탭이 됨)→붙여넣기가
    새 탭에 적용되고 소스 탭은 그대로. 합성 클립보드가 아니라 _copy_current_screenshot
    이 실제로 클립보드에 올린 것을 _paste_to_current_screenshot 가 되읽는 라운드 트립."""
    from PySide6.QtCore import QRect
    from screen_recorder.ui.edit_tab import EditTab
    from screen_recorder.ui.library_model import EntryKind

    win = _win(qtbot, tmp_path)

    # 1) 소스 탭 + 선택 영역
    win._on_screenshot_captured(_solid(60, 40, 0xFF3366CC), "region")
    src = win._current_screenshot_tab()
    src.selection.set_rect(QRect(0, 0, 20, 15))

    # 2) 진짜 복사 (selection 영역 → 클립보드)
    win._copy_current_screenshot()

    # 3) '새 캔버스' — _on_file_new 와 동일 경로 (모달 다이얼로그만 생략)
    new_tab = EditTab.from_blank(QSize(30, 25))
    entry = win.library_model.add(
        EntryKind.IMAGE, thumbnail=_solid(8, 8, 0xFF000000),
        source_label="new", display_name="새 캔버스", origin="opened",
    )
    win.tab_area.add_image_tab(new_tab, entry_id=entry.id, display_name="새 캔버스")

    # 새 탭이 현재 탭이어야 paste 가 새 탭을 노린다 (이 보장이 깨지면 사용자 버그 재발).
    assert win._current_screenshot_tab() is new_tab
    before_new = len(new_tab.stack.layers)
    before_src = len(src.stack.layers)

    # 4) 붙여넣기
    win._paste_to_current_screenshot()

    assert len(new_tab.stack.layers) == before_new + 1   # 새 탭에 추가
    assert len(src.stack.layers) == before_src           # 소스 탭은 불변
    assert new_tab.stack.active_layer().pixmap.size() == QSize(20, 15)  # 선택 크기
    win.close()
