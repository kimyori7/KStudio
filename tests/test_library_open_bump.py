"""파일을 열면 라이브러리 맨 위로 — 이미 라이브러리에 있어도 (2026-07-14 사용자 요청).

새 파일은 원래 맨 위에 추가되지만, 이미 있는 파일을 다시 열면 순서가 그대로였다.
모든 열기 경로(중복 재사용 분기)가 move_to_top 을 호출해야 한다.

복원 순서: 수동 재정렬을 지원하므로 시작 시 created_at 재정렬을 하지 않고
저장된 순서 그대로 복원해야 한다.
"""
from pathlib import Path

from PySide6.QtGui import QImage


def _save_png(path: Path, argb: int) -> Path:
    img = QImage(16, 16, QImage.Format_ARGB32)
    img.fill(argb)
    img.save(str(path), "PNG")
    return path


def _names(win):
    return [e.display_name for e in win.library_model.entries()]


def test_register_dropped_document_bumps_existing_to_top(qtbot, tmp_path):
    """중복 문서 재등록 → 맨 위로 + 순서 변경이 저장 타이머를 트리거."""
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    a = tmp_path / "a.md"
    a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("b", encoding="utf-8")
    win._register_dropped_document(a)
    win._register_dropped_document(b)
    assert _names(win) == ["b.md", "a.md"]
    win._library_save_timer.stop()
    win._register_dropped_document(a)          # 중복 재등록 → 맨 위로, 추가 X
    assert _names(win) == ["a.md", "b.md"]
    # 재시작 후에도 유지되도록 순서 변경이 settings 저장을 예약해야 한다.
    assert win._library_save_timer.isActive()
    win.close()


def test_drop_duplicate_image_bumps_to_top(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    pa = _save_png(tmp_path / "a.png", 0xFF111111)
    pb = _save_png(tmp_path / "b.png", 0xFF222222)
    win._open_image_path(pa)
    win._open_image_path(pb)
    assert _names(win) == ["b.png", "a.png"]
    win._on_library_files_dropped([str(pa)])   # 중복 드롭 → 맨 위로
    assert _names(win) == ["a.png", "b.png"]
    win.close()


def test_open_markdown_already_open_bumps_to_top(qtbot, tmp_path):
    """탭이 이미 열려 있는 문서를 다시 열어도(더블클릭/전달) 맨 위로."""
    from screen_recorder.app.main import build_main_window
    win = build_main_window()
    qtbot.addWidget(win)
    a = tmp_path / "a.md"
    a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("b", encoding="utf-8")
    win._open_markdown_path(a)
    win._open_markdown_path(b)
    assert _names(win) == ["b.md", "a.md"]
    win._open_markdown_path(a)                 # 이미 탭 열림 → 포커스 + 맨 위로
    assert _names(win) == ["a.md", "b.md"]
    win.close()


