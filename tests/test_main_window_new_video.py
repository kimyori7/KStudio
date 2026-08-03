"""파일 → 새 영상 프로젝트 — 빈 타임라인 탭 + 라이브러리 entry 생성."""
from pathlib import Path

import pytest

from screen_recorder.core.settings import AppSettings
from screen_recorder.ui.main_window import MainWindow


@pytest.fixture
def ffmpeg_stub(tmp_path):
    p = tmp_path / "ffmpeg.exe"
    p.write_bytes(b"")
    return p


@pytest.fixture
def window(qtbot, ffmpeg_stub, tmp_path, monkeypatch):
    s = AppSettings()
    # 사이드카(=프로젝트 파일) 폴더를 테스트 tmp 로 — 실제 %APPDATA% 를 건드리지 않는다.
    w = MainWindow(s, ffmpeg_stub)
    qtbot.addWidget(w)
    monkeypatch.setattr(w, "_resolve_sidecar_dir", lambda: tmp_path / "sidecars")
    return w


def test_new_video_action_exists_in_file_menu(window):
    """「새 영상 프로젝트」가 파일 메뉴에 있고 단축키가 붙어 있다."""
    action = window.menu_bar.new_video_action
    assert "영상" in action.text()
    assert action.shortcut().toString() == "Ctrl+Shift+N"


def test_new_video_opens_blank_video_tab(window, qtbot):
    """실행 → 빈 트랙의 영상 탭이 열리고 라이브러리에 항목이 생긴다."""
    before = len(window.library_model.entries())
    window.menu_bar.new_video_requested.emit()

    tab = window.tab_area.current_video_tab()
    assert tab is not None
    assert tab.is_blank_project() is True
    assert tab.sidecar().video_track == []
    assert len(window.library_model.entries()) == before + 1


def test_two_new_video_projects_do_not_share_a_file(window, tmp_path):
    """연속으로 두 번 만들어도 서로 다른 파일 — 나중 것이 먼저 것을 덮어쓰면 안 된다.

    프로젝트 파일을 첫 편집 때 만들면 둘 다 「새 영상 1」을 잡는다. 그래서 만드는
    즉시 빈 사이드카를 써서 이름을 선점한다.
    """
    window.menu_bar.new_video_requested.emit()
    first = window.tab_area.current_video_tab()._edit_controller.project_path()
    window.menu_bar.new_video_requested.emit()
    second = window.tab_area.current_video_tab()._edit_controller.project_path()

    assert first is not None and second is not None
    assert first != second
    assert first.exists() and second.exists()


def test_export_of_empty_blank_project_is_refused(window, monkeypatch):
    """클립이 하나도 없으면 내보내기를 조용히 진행하지 않고 이유를 알린다."""
    warnings: list[str] = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a[2] if len(a) > 2 else "")),
    )
    window.menu_bar.new_video_requested.emit()
    window._on_export_video()
    assert any("클립" in w for w in warnings)


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


def test_reopen_blank_project_from_library_after_closing_tab(window, qtbot):
    """탭을 닫은 뒤 라이브러리 항목을 클릭하면 그 프로젝트가 다시 열린다.

    되열기 경로가 없으면 "만들 수는 있는데 다시 못 여는" 반쪽 기능이 된다.
    """
    tab, project = _make_blank_project(window)
    entry = window._find_library_entry_for_path(project)
    assert entry is not None, "빈 프로젝트도 라이브러리에 경로와 함께 남아야 한다"

    _close_tab(window, entry.id)

    window._open_entry(entry.id)
    reopened = window.tab_area.current_video_tab()
    assert reopened is not None
    assert reopened.is_blank_project() is True
    assert reopened._edit_controller.project_path() == project


def test_reopen_preserves_clips(window, qtbot, tmp_path, monkeypatch):
    """다시 열면 붙여 놓은 클립이 그대로 있다."""
    import screen_recorder.services.media_probe as media_probe
    monkeypatch.setattr(media_probe, "probe_duration_ms", lambda _src: 5000)
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000)

    tab, project = _make_blank_project(window)
    tab._on_track_insert_files([str(clip)], 0)
    tab._edit_controller.save_now()
    entry = window._find_library_entry_for_path(project)
    _close_tab(window, entry.id)

    window._open_entry(entry.id)
    reopened = window.tab_area.current_video_tab()
    assert len(reopened.sidecar().video_track) == 1
    assert reopened.sidecar().video_track[0].src == str(clip)


def test_open_project_file_directly(window, qtbot):
    """파일 → 열기 로 프로젝트 .kstudio 를 골라도 열린다 ("원본 영상 없음" 아님)."""
    tab, project = _make_blank_project(window)
    entry = window._find_library_entry_for_path(project)
    _close_tab(window, entry.id)

    window._open_path(project)
    reopened = window.tab_area.current_video_tab()
    assert reopened is not None
    assert reopened.is_blank_project() is True


def test_reopen_focuses_existing_tab_instead_of_duplicating(window, qtbot):
    """이미 열려 있으면 새 탭을 만들지 않는다 — 두 탭이 같은 파일을 덮어쓰면 작업이 갈린다."""
    tab, project = _make_blank_project(window)
    before = window.tab_area.count()
    window._open_path(project)
    assert window.tab_area.count() == before
    assert window.tab_area.current_video_tab() is tab


def test_project_file_restores_as_video_entry_not_image(window, tmp_path):
    """재시작 복원 — .kstudio 확장자만 보면 이미지로 잘못 분류된다 (magic 으로 구분)."""
    from screen_recorder.ui.library_model import EntryKind

    _tab, project = _make_blank_project(window)
    assert window._kind_for_path(project, fallback=EntryKind.IMAGE) is EntryKind.VIDEO


def test_missing_project_file_reports_instead_of_opening_empty(window, monkeypatch):
    """파일이 외부에서 지워졌으면 빈 프로젝트를 새로 열지 않고 알린다.

    조용히 열면 사용자는 "작업이 통째로 날아갔다" 로 본다 (같은 이름의 빈 탭).
    """
    warnings: list[str] = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a[2] if len(a) > 2 else "")),
    )
    _tab, project = _make_blank_project(window)
    entry = window._find_library_entry_for_path(project)
    _close_tab(window, entry.id)
    project.unlink()

    before = window.tab_area.count()
    window._open_entry(entry.id)

    assert window.tab_area.count() == before
    assert any("찾을 수 없" in w for w in warnings)
    assert window._find_library_entry_for_path(project) is None
