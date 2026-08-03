"""빈 영상 프로젝트를 라이브러리에서 삭제 / 되돌리기.

이 저장소의 알려진 함정 때문에 파일을 분리했다 — `_on_library_delete` 는 전역으로
deferred delete 를 돌리는데, 같은 프로세스에서 앞선 테스트가 VideoTab 을 닫아 두었으면
그 파괴가 여기서 일어나며 러너가 access violation 으로 죽는다. 단독 파일이면 안전하다.
"""
from pathlib import Path

import pytest

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    ff = tmp_path / "ffmpeg.exe"
    ff.write_bytes(b"")
    w = MainWindow(AppSettings(), ff)
    qtbot.addWidget(w)
    monkeypatch.setattr(w, "_resolve_sidecar_dir", lambda: tmp_path / "sidecars")
    return w


def _close_tab(window, entry_id: int) -> None:
    """탭의 X 와 같은 경로로 닫는다 — removeTab 직접 호출은 내부 장부를 안 지운다."""
    idx = window.tab_area.find_index_by_entry(entry_id)
    assert idx >= 0
    window.tab_area.tabCloseRequested.emit(idx)


def _make_blank_project(window):
    """새 영상 프로젝트 1개를 만들고 (탭, 프로젝트 경로) 반환."""
    window.menu_bar.new_video_requested.emit()
    tab = window.tab_area.current_video_tab()
    return tab, tab._edit_controller.project_path()


def test_library_delete_trashes_project_and_undo_restores_it(window, monkeypatch):
    """Shift+Del 은 프로젝트 파일 자체를 휴지통으로 — Ctrl+Z 로 되돌아온다.

    빈 프로젝트는 entry.path 가 곧 문서 전체라, 되돌릴 수 없으면 한 번의 실수로
    타임라인이 통째로 사라진다.
    """
    trashed: list[str] = []
    restored: list[str] = []
    import screen_recorder.ui.main_window as mw
    monkeypatch.setattr(mw.MainWindow, "_send_to_trash_with_retry",
                        lambda self, p: (trashed.append(str(p)), Path(p).unlink())[0])
    import screen_recorder.core.recycle_bin as rb
    monkeypatch.setattr(rb, "is_supported", lambda: True)
    monkeypatch.setattr(
        rb, "restore",
        lambda p: (restored.append(str(p)), Path(p).write_text("{}", encoding="utf-8"), (True, ""))[2],
    )

    _tab, project = _make_blank_project(window)
    entry = window._find_library_entry_for_path(project)
    # 탭을 먼저 닫는다 — 삭제 경로 안에서 VideoTab 이 파괴되면 Qt teardown 이
    # 다른 테스트의 위젯까지 건드려 러너가 죽는다 (이 저장소의 알려진 함정).
    _close_tab(window, entry.id)
    window._on_library_delete(entry.id)
    assert trashed == [str(project)]
    assert window._find_library_entry_for_path(project) is None

    window._on_library_undelete()
    assert restored == [str(project)]
    assert window._find_library_entry_for_path(project) is not None
