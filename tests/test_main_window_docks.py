"""MainWindow 의 QDockWidget 구조 — 라이브러리·레이어·녹화 상태 모두 dockable."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget


def test_main_window_has_all_four_docks(qtbot, qapp):
    """라이브러리/레이어/녹화상태/인스펙터 — 4개 QDockWidget 이 모두 등록되어 있어야 한다."""
    from screen_recorder.app.main import build_main_window
    w = build_main_window()
    qtbot.addWidget(w)
    for name in ("library_dock", "layers_dock", "record_status_dock", "inspector_dock"):
        assert hasattr(w, name), f"{name} 가 MainWindow 에 없음"
        dock = getattr(w, name)
        assert isinstance(dock, QDockWidget), f"{name} 가 QDockWidget 가 아님"
        # objectName 은 saveState/restoreState 식별자 — 비어 있으면 상태 영속 불가.
        assert dock.objectName(), f"{name}.objectName 이 비어 있음"


def test_docks_allow_floating_and_movable(qtbot, qapp):
    """기본 QDockWidget 기능 — 부동(floating) + 이동 가능. 사용자가 떼어내거나 옮길 수 있어야 한다."""
    from screen_recorder.app.main import build_main_window
    w = build_main_window()
    qtbot.addWidget(w)
    for name in ("library_dock", "layers_dock", "record_status_dock"):
        dock = getattr(w, name)
        features = dock.features()
        assert features & QDockWidget.DockWidgetMovable, f"{name} 가 이동 불가"
        assert features & QDockWidget.DockWidgetFloatable, f"{name} 가 부동 불가"


def test_save_restore_state_round_trip(qtbot, qapp):
    """saveState/restoreState 가 QByteArray 로 직렬화·복원 가능해야 한다 (레이아웃 영속)."""
    from screen_recorder.app.main import build_main_window
    w = build_main_window()
    qtbot.addWidget(w)
    state = w.saveState()
    assert state is not None
    assert len(bytes(state)) > 0
    assert w.restoreState(state) is True
