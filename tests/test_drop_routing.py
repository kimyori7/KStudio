"""외부 파일 드롭 라우팅 검증 (사용자 요청 2026-05-29).

요구사항 3가지:
  1. 영상→영상 라이브러리 / 이미지→이미지 라이브러리 / 문서→문서 라이브러리
  2. 드롭 완료 시 그 모드로 전환
  3. 방금 드롭한 파일 보여주기 (해당 탭이 currentWidget 으로 포커스)

drop 라우팅은 이미 HEAD 에 구현·커밋돼 있음. 이 테스트는 working tree 기준으로
세 경로가 모두 실제로 동작하는지(특히 미커밋 markdown 변경이 깨뜨리지 않았는지) 확인.
"""
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QMimeData, QUrl
from PySide6.QtGui import QImage, QDropEvent

from screen_recorder.ui.main_window import MainWindow
from screen_recorder.ui.library_model import EntryKind
from screen_recorder.ui.mode_controller import AppMode
from screen_recorder.ui.tab_area import VideoTab
from screen_recorder.ui.edit_tab import EditTab
from screen_recorder.ui.markdown_tab import MarkdownTab
from screen_recorder.core.settings import AppSettings


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def _make_image(tmp_path: Path) -> Path:
    p = tmp_path / "shot.png"
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    assert img.save(str(p), "PNG")
    return p


def _make_video(tmp_path: Path) -> Path:
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42")   # 최소 더미 (probe 는 비동기·무해)
    return p


def _make_markdown(tmp_path: Path) -> Path:
    p = tmp_path / "note.md"
    p.write_text("# 제목\n본문", encoding="utf-8")
    return p


def test_drop_image_routes_to_image_library_and_mode(w, tmp_path):
    p = _make_image(tmp_path)
    w._open_path(p)
    assert len(w.library_model.entries(EntryKind.IMAGE)) == 1
    assert w.mode_controller.mode() is AppMode.IMAGE
    assert isinstance(w.tab_area.currentWidget(), EditTab)


def test_drop_video_routes_to_video_library_and_mode(w, tmp_path):
    p = _make_video(tmp_path)
    w._open_path(p)
    assert len(w.library_model.entries(EntryKind.VIDEO)) == 1
    assert w.mode_controller.mode() is AppMode.VIDEO
    assert isinstance(w.tab_area.currentWidget(), VideoTab)


def test_drop_markdown_routes_to_document_library_and_mode(w, tmp_path):
    p = _make_markdown(tmp_path)
    w._open_path(p)
    assert len(w.library_model.entries(EntryKind.DOCUMENT)) == 1
    assert w.mode_controller.mode() is AppMode.DOCUMENT
    assert isinstance(w.tab_area.currentWidget(), MarkdownTab)


def test_real_drop_event_markdown(w, tmp_path):
    """실제 QDropEvent 진입점 — 미커밋 markdown 변경 경로가 가장 신선/취약."""
    p = _make_markdown(tmp_path)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p))])
    ev = QDropEvent(
        QPointF(10, 10), Qt.CopyAction, mime,
        Qt.LeftButton, Qt.NoModifier,
    )
    w.dropEvent(ev)
    assert ev.isAccepted()
    assert w.mode_controller.mode() is AppMode.DOCUMENT
    assert isinstance(w.tab_area.currentWidget(), MarkdownTab)
