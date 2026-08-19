"""포커스가 영상 탭 밖에 있어도 Ctrl+C / Ctrl+V 가 현재 영상 탭에 닿는다.

2026-08-19 사용자 보고: "A 영상에서 이만큼 떼서 B 영상에 붙이고 싶어서". 재현해 보니
복사·붙여넣기 기능 자체는 있었지만, Qt 가 키 이벤트를 *포커스 위젯* 의 부모 사슬로만
올려 보내기 때문에 라이브러리 목록에 포커스가 남아 있으면 VideoTab 까지 닿지 못하고
아무 일도 일어나지 않았다. 라이브러리에서 영상 B 를 여는 흔한 흐름이 바로 그 상태다.

기존 tests/test_video_tab_clip_paste.py 는 키를 탭에 직접 넣어(`keyClick(tab, ...)`)
포커스 경로를 건너뛰므로 이 문제를 잡지 못했다 — 여기서는 창에 넣는다.

MainWindow 를 띄우므로 파일을 분리했다 (탭 파괴가 다른 테스트와 얽히면 러너가 죽는다).
"""
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget

from screen_recorder.core.settings import AppSettings
from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.main_window import MainWindow
from screen_recorder.ui.video.clip_clipboard import clipboard


@pytest.fixture(autouse=True)
def clean_clipboard():
    clipboard().clear()
    yield
    clipboard().clear()


@pytest.fixture
def window(qtbot, tmp_path):
    ff = tmp_path / "ffmpeg.exe"
    ff.write_bytes(b"")
    w = MainWindow(AppSettings(), ff)
    qtbot.addWidget(w)
    w._resolve_sidecar_dir = lambda: tmp_path / "sidecars"
    return w


def _video_tab_with_clip(window, tmp_path: Path, name: str):
    """빈 영상 프로젝트 탭 1개 + 트랙에 클립 1개 (10초)."""
    window.menu_bar.new_video_requested.emit()
    tab = window.tab_area.current_video_tab()
    tab.set_edit_mode(True)
    src = tmp_path / f"{name}.mp4"
    src.write_bytes(b"x" * 200_000)
    tab._edit_controller.insert_segment(
        0, VideoSegment(src=str(src), src_duration_ms=10_000, start_ms=0)
    )
    return tab


def _library_list(window) -> QListWidget:
    return window.library_dock.widget().findChildren(QListWidget)[0]


def test_paste_works_when_focus_is_in_the_library(window, qtbot, tmp_path):
    """라이브러리 목록에 포커스가 있어도 Ctrl+V 가 현재 영상 탭에 붙는다."""
    tab_a = _video_tab_with_clip(window, tmp_path, "a")
    tab_b = _video_tab_with_clip(window, tmp_path, "b")

    window.tab_area.setCurrentWidget(tab_a)
    tab_a._active_kind = "segment"
    tab_a._active_id = tab_a.sidecar().video_track[0].id
    tab_a.copy_active_to_clipboard()
    assert clipboard().kind() == "segment"

    window.tab_area.setCurrentWidget(tab_b)
    lib = _library_list(window)
    lib.setFocus(Qt.MouseFocusReason)
    assert not tab_b.isAncestorOf(lib), "라이브러리는 탭 밖의 위젯이다"

    before = len(tab_b.sidecar().video_track)
    qtbot.keyClick(lib, Qt.Key_V, Qt.ControlModifier)
    assert len(tab_b.sidecar().video_track) == before + 1


def test_copy_works_when_focus_is_in_the_library(window, qtbot, tmp_path):
    """선택은 트랙에 있고 포커스만 밖에 있는 상태의 Ctrl+C."""
    tab = _video_tab_with_clip(window, tmp_path, "a")
    tab._active_kind = "segment"
    tab._active_id = tab.sidecar().video_track[0].id

    lib = _library_list(window)
    lib.setFocus(Qt.MouseFocusReason)
    qtbot.keyClick(lib, Qt.Key_C, Qt.ControlModifier)
    assert clipboard().kind() == "segment"


def test_text_widgets_keep_their_own_copy(window, qtbot, tmp_path):
    """텍스트 입력칸의 Ctrl+C 는 가로채지 않는다 — 글자 복사가 먼저다.

    QLineEdit 이 Ctrl+C 를 스스로 처리해 창까지 올라오지 않으므로 클립 복사가 일어나지
    않아야 한다. (WindowShortcut 컨텍스트의 QShortcut 을 쓰지 않는 이유가 이것이다.)
    """
    from PySide6.QtWidgets import QLineEdit

    tab = _video_tab_with_clip(window, tmp_path, "a")
    tab._active_kind = "segment"
    tab._active_id = tab.sidecar().video_track[0].id

    edit = QLineEdit(window)
    edit.setText("글자")
    edit.selectAll()
    edit.setFocus(Qt.MouseFocusReason)
    qtbot.keyClick(edit, Qt.Key_C, Qt.ControlModifier)
    assert clipboard().kind() is None, "클립보드에 클립이 담기면 안 된다"
