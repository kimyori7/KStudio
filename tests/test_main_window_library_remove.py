"""Del/Shift+Del 분기: 라이브러리 제외 vs 휴지통.

Del 단독은 디스크 파일을 건드리지 않고 라이브러리 목록에서만 제거.
Shift+Del 은 send2trash 로 휴지통 이동 (기존 동작).
"""
from __future__ import annotations
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings


def _img() -> QImage:
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_library_remove_does_not_touch_disk(w, tmp_path):
    """Del 단독 → 라이브러리에서만 제외, 디스크 파일은 그대로."""
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    files = list(tmp_path.glob("*.png"))
    assert len(files) == 1
    saved = files[0]
    # 라이브러리에 1 항목 있음.
    entries = w.library_model.entries()
    assert len(entries) == 1
    entry_id = entries[0].id
    # Del → _on_library_remove.
    w._on_library_remove(entry_id)
    # 디스크 파일은 그대로.
    assert saved.exists()
    # 라이브러리에서는 제거됨.
    assert w.library_model.get(entry_id) is None


def test_library_delete_sends_to_trash(w, tmp_path, monkeypatch):
    """Shift+Del → _on_library_delete → send2trash 호출 + 라이브러리에서 제거."""
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    files = list(tmp_path.glob("*.png"))
    saved = files[0]
    entry_id = w.library_model.entries()[0].id

    calls: list[str] = []
    def fake_send(path: str) -> None:
        calls.append(path)
        # send2trash 가 실제로 파일을 제거하듯 흉내내기 — 라이브러리 동작 테스트 목적이므로 OK.
        Path(path).unlink(missing_ok=True)

    monkeypatch.setattr(
        "send2trash.send2trash", fake_send
    )
    w._on_library_delete(entry_id)
    # send2trash 가 호출됐고, 라이브러리에서 제거됨.
    assert calls == [str(saved)]
    assert w.library_model.get(entry_id) is None


def test_undelete_after_remove_skips_recycle_restore(w, tmp_path, monkeypatch):
    """Del(라이브러리에서만 제외) 후 Ctrl+Z → 휴지통 restore 호출 X, 그냥 라이브러리에 재등록."""
    w._on_screenshot_captured(_img(), "region")
    w._save_current_screenshot()
    entry_id = w.library_model.entries()[0].id
    w._on_library_remove(entry_id)
    assert w.library_model.get(entry_id) is None

    rb_calls: list = []
    def fake_restore(p):
        rb_calls.append(p)
        return True, ""
    monkeypatch.setattr(
        "screen_recorder.core.recycle_bin.restore", fake_restore
    )

    w._on_library_undelete()
    # restore 안 부름 — 파일은 디스크에 그대로.
    assert rb_calls == []
    # 라이브러리에 다시 등록됨 (새 id).
    assert len(w.library_model.entries()) == 1
