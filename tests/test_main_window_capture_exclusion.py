"""메인 창 캡처 제외(WDA_EXCLUDEFROMCAPTURE)를 "우리가 화면을 읽는 동안"만 거는 배선.

Qt offscreen 에서는 affinity 자체를 못 잰다 — 시그널·호출 횟수·depth 상태만 검증.
exclude/include 는 main_window 네임스페이스에서 mock 으로 교체한다 (모듈 속성 변경은
monkeypatch 로만 — 세션 잔류 방지).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from screen_recorder.ui import main_window as mw
from screen_recorder.ui.main_window import MainWindow
from screen_recorder.core.settings import AppSettings
from screen_recorder.capture.targets import RegionTarget, Rect


@pytest.fixture
def w(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    s = AppSettings()
    # 라이브러리 시작 시 디스크 스캔이 사용자 실제 저장 폴더를 읽지 않도록 tmp_path 격리.
    s.screenshot.save_dir = str(tmp_path / "shots")
    s.general.output_dir = str(tmp_path / "videos")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def capture_flags(monkeypatch):
    """main_window 네임스페이스의 exclude/include 를 카운터 mock 으로 교체."""
    exclude = MagicMock(return_value=True)
    include = MagicMock(return_value=True)
    monkeypatch.setattr(mw, "exclude_from_capture", exclude)
    monkeypatch.setattr(mw, "include_in_capture", include)
    return exclude, include


def _patch_start(monkeypatch, w):
    """start_recording 을 무해한 mock 으로, _build_target 은 고정 영역으로."""
    start = MagicMock()
    monkeypatch.setattr(w.controller, "start_recording", start)
    monkeypatch.setattr(
        w, "_build_target", lambda: RegionTarget(Rect(0, 0, 100, 100))
    )
    return start


def test_depth_nesting(w, capture_flags, caplog):
    """begin, begin, end, end → exclude 는 첫 begin 한 번, include 는 마지막 end 한 번.
    depth 0 에서 한 번 더 end → 경고만, 상태 불변."""
    import logging
    exclude, include = capture_flags

    w._begin_self_capture()
    w._begin_self_capture()
    assert w._capture_depth == 2
    assert exclude.call_count == 1
    assert include.call_count == 0

    w._end_self_capture()
    w._end_self_capture()
    assert w._capture_depth == 0
    assert include.call_count == 1

    with caplog.at_level(logging.WARNING, logger="screen_recorder.ui.main_window"):
        w._end_self_capture()
    assert w._capture_depth == 0
    assert include.call_count == 1  # include 는 추가로 안 나간다
    assert any("_end_self_capture" in r.message for r in caplog.records)


def test_snap_signals_drive_exclusion(w, capture_flags):
    """스크린샷 구간 — about_to_snap → exclude 1회, snap_done → include 1회."""
    exclude, include = capture_flags
    w._screenshot_ctrl.about_to_snap.emit()
    assert w._capture_depth == 1
    assert exclude.call_count == 1
    assert include.call_count == 0

    w._screenshot_ctrl.snap_done.emit()
    assert w._capture_depth == 0
    assert include.call_count == 1


def test_recording_lease_released_once(w, capture_flags):
    """lease 는 중복 획득해도 depth 는 1 — capture_stopped 가 두 번 나도 include 는 한 번."""
    exclude, include = capture_flags
    w._acquire_recording_lease()
    w._acquire_recording_lease()
    assert w._recording_lease is True
    assert w._capture_depth == 1
    assert exclude.call_count == 1

    w.controller.capture_stopped.emit()
    w.controller.capture_stopped.emit()
    assert w._recording_lease is False
    assert w._capture_depth == 0
    assert include.call_count == 1


def test_keep_visible_skips_exclusion(w, capture_flags):
    """「내 화면에 보이기」 ON 이면 depth 가 올라가도 exclude 는 안 건다."""
    exclude, include = capture_flags
    w.app_settings.preferences.keep_visible_during_capture = True
    w._begin_self_capture()
    assert w._capture_depth == 1
    assert exclude.call_count == 0
    w._end_self_capture()
    assert w._capture_depth == 0


def test_pending_start_cancelled_by_stop(w, capture_flags, monkeypatch, qtbot):
    """시작 예약 직후 stop → 예약 취소: start_recording 은 안 불리고 lease 는 반납."""
    exclude, include = capture_flags
    start = _patch_start(monkeypatch, w)

    w._on_start_clicked()
    assert w._start_pending is True
    assert w._capture_depth == 1
    assert exclude.call_count == 1

    w._on_stop_clicked()
    assert w._start_cancelled is True

    qtbot.wait(120)  # SNAP_SETTLE_MS(50) 지나 singleShot 이 발화할 시간
    assert start.call_count == 0
    assert w._start_pending is False
    assert w._capture_depth == 0
    assert include.call_count == 1


def test_start_unavailable_target_releases_lease(w, capture_flags, monkeypatch, qtbot):
    """start_recording 이 예외 없이 IDLE 로 돌아오면(target unavailable) lease 를 반납."""
    exclude, include = capture_flags
    start = _patch_start(monkeypatch, w)  # no-op — state 는 IDLE 유지

    w._on_start_clicked()
    assert w._capture_depth == 1
    qtbot.wait(120)
    assert start.call_count == 1
    assert w._capture_depth == 0
    assert include.call_count == 1
