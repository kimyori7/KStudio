from unittest.mock import MagicMock, patch
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage

from screen_recorder.capture.targets import Rect
from screen_recorder.screenshot.controller import ScreenshotController


def _fake_image(w=200, h=100):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    return img


def test_full_capture_emits_entire_snapshot(qtbot):
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    fake_img = _fake_image(400, 300)

    # capture_full 은 snapshot_monitor 로 간다 (기존 `after_snap is self._handle_full`
    # 비교는 bound method 라 항상 False 였고 그 버그로 가상 데스크톱 전체가 찍혔음).
    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=fake_img):
        with qtbot.waitSignal(ctrl.captured, timeout=2000) as blocker:
            ctrl.capture_full()

    emitted_img, label = blocker.args
    assert emitted_img.width() == 400
    assert emitted_img.height() == 300
    assert label == "fullscreen"


def test_region_capture_crops_using_selector_emit(qtbot):
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    fake_img = _fake_image(400, 300)

    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=fake_img):
        with patch("screen_recorder.screenshot.controller.virtual_desktop_bounds") as bounds_mock:
            from PySide6.QtCore import QRect
            bounds_mock.return_value = QRect(0, 0, 400, 300)
            with patch("screen_recorder.screenshot.controller.RegionSelector") as SelectorCls:
                sel = MagicMock()
                SelectorCls.return_value = sel
                # 드래그 결과를 즉시 시뮬레이션
                def fake_show():
                    handler = sel.region_selected.connect.call_args[0][0]
                    handler(Rect(100, 50, 80, 60))
                sel.show.side_effect = fake_show

                with qtbot.waitSignal(ctrl.captured, timeout=2000) as blocker:
                    ctrl.capture_region()

    emitted_img, label = blocker.args
    assert emitted_img.width() == 80
    assert emitted_img.height() == 60
    assert label == "region"


def test_cancel_region_does_not_emit_captured(qtbot):
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    captured_calls = []
    ctrl.captured.connect(lambda *a: captured_calls.append(a))
    fake_img = _fake_image()

    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=fake_img):
        with patch("screen_recorder.screenshot.controller.RegionSelector") as SelectorCls:
            sel = MagicMock()
            SelectorCls.return_value = sel

            def fake_show():
                handler = sel.cancelled.connect.call_args[0][0]
                handler()
            sel.show.side_effect = fake_show

            ctrl.capture_region()
            qtbot.wait(100)

    assert captured_calls == []


def test_main_window_not_touched_during_capture(qtbot):
    """캡처 시 메인 창 상태를 건드리지 않는다 — WDA_EXCLUDEFROMCAPTURE + RegionSelector
    가 알아서 가려주므로 hide/minimize/opacity 모두 불필요. 깜박임 부작용 회피."""
    main = MagicMock()
    main.isMinimized.return_value = False
    main.isMaximized.return_value = False
    main.isVisible.return_value = True
    ctrl = ScreenshotController(main_window=main, viewer_getter=lambda: None)

    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=_fake_image()):
        with qtbot.waitSignal(ctrl.captured, timeout=2000):
            ctrl.capture_full()

    main.hide.assert_not_called()
    main.showMinimized.assert_not_called()
    main.setWindowOpacity.assert_not_called()


# ----- about_to_snap / snap_done 짝 + _busy (SNAP_SETTLE_MS 대기 중 요청 무시) -----

def test_full_capture_uses_monitor_index(qtbot):
    """capture_full(0) 은 snapshot_monitor(0) 을 정확히 1회, 가상 데스크톱은 0회.

    `after_snap is self._handle_full` 는 bound method 라 항상 False 였다 — 그래서
    모니터를 골라도 늘 가상 데스크톱 전체가 찍히던 버그의 회귀 방지 (kind 로 대체)."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    fake_img = _fake_image(400, 300)
    with patch("screen_recorder.screenshot.controller.snapshot_monitor") as sm, \
         patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop") as sv:
        sm.return_value = fake_img
        sv.return_value = fake_img
        with qtbot.waitSignal(ctrl.captured, timeout=2000):
            ctrl.capture_full(0)
    sm.assert_called_once_with(0)
    sv.assert_not_called()


def test_snap_signals_pair_full(qtbot):
    """전체 스냅 성공: about_to_snap 1회 + snap_done 1회 (정확히 짝)."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    about, done = [], []
    ctrl.about_to_snap.connect(lambda: about.append(1))
    ctrl.snap_done.connect(lambda: done.append(1))
    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=_fake_image()):
        with qtbot.waitSignal(ctrl.captured, timeout=2000):
            ctrl.capture_full()
    assert len(about) == 1
    assert len(done) == 1


def test_snap_signals_pair_region(qtbot):
    """영역 스냅 성공: about_to_snap 1회 + snap_done 1회. snap_done 은 selector 가
    뜨기 전(스냅 직후)에 난다 — 영역 선택이 길어도 메인 창은 가려져 있으므로."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    about, done = [], []
    ctrl.about_to_snap.connect(lambda: about.append(1))
    ctrl.snap_done.connect(lambda: done.append(1))
    fake_img = _fake_image(400, 300)
    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=fake_img):
        with patch("screen_recorder.screenshot.controller.virtual_desktop_bounds",
                   return_value=QRect(0, 0, 400, 300)):
            with patch("screen_recorder.screenshot.controller.RegionSelector") as SelectorCls:
                sel = MagicMock()
                SelectorCls.return_value = sel

                def fake_show():
                    handler = sel.region_selected.connect.call_args[0][0]
                    handler(Rect(100, 50, 80, 60))
                sel.show.side_effect = fake_show

                with qtbot.waitSignal(ctrl.captured, timeout=2000):
                    ctrl.capture_region()
    assert len(about) == 1
    assert len(done) == 1


def test_snap_signals_pair_null(qtbot):
    """빈 이미지(QImage()) 여도 about_to_snap/snap_done 은 1회씩 짝으로 (취소로 이어짐)."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    about, done = [], []
    ctrl.about_to_snap.connect(lambda: about.append(1))
    ctrl.snap_done.connect(lambda: done.append(1))
    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=QImage()):
        with qtbot.waitSignal(ctrl.cancelled, timeout=2000):
            ctrl.capture_full()
    assert len(about) == 1
    assert len(done) == 1


def test_snap_signals_pair_exception(qtbot):
    """스냅 함수가 예외를 던져도 snap_done 은 finally 로 정확히 1회, 취소로 이어진다."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    about, done = [], []
    ctrl.about_to_snap.connect(lambda: about.append(1))
    ctrl.snap_done.connect(lambda: done.append(1))
    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop",
               side_effect=RuntimeError("스냅 실패")):
        with qtbot.waitSignal(ctrl.cancelled, timeout=2000):
            ctrl.capture_region()
    assert len(about) == 1
    assert len(done) == 1


def test_second_request_ignored_while_pending(qtbot):
    """SNAP_SETTLE_MS 대기 중 두 번째 요청(단축키 연타)은 _busy 가 막는다.

    두 번째 capture_full 이 _monitor_index_for_capture 나 타이머를 덮어쓰지 않도록
    about_to_snap 은 1회여야 한다."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    about, done = [], []
    ctrl.about_to_snap.connect(lambda: about.append(1))
    ctrl.snap_done.connect(lambda: done.append(1))
    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=_fake_image()):
        with qtbot.waitSignal(ctrl.captured, timeout=2000):
            ctrl.capture_full()
            ctrl.capture_full()
    assert len(about) == 1
    assert len(done) == 1


def test_busy_clears_after_region_cancel(qtbot):
    """영역 선택 취소 뒤에는 _busy 가 풀려 capture_full() 이 다시 동작한다."""
    ctrl = ScreenshotController(main_window=None, viewer_getter=lambda: None)
    fake_img = _fake_image(400, 300)

    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=fake_img):
        with patch("screen_recorder.screenshot.controller.RegionSelector") as SelectorCls:
            sel = MagicMock()
            SelectorCls.return_value = sel

            def fake_show():
                handler = sel.cancelled.connect.call_args[0][0]
                handler()
            sel.show.side_effect = fake_show

            with qtbot.waitSignal(ctrl.cancelled, timeout=2000):
                ctrl.capture_region()

    # 취소(on_cancelled) 첫 줄에서 _busy = False 가 됐으므로 다음 요청이 진행된다
    with patch("screen_recorder.screenshot.controller.snapshot_monitor", return_value=fake_img):
        with qtbot.waitSignal(ctrl.captured, timeout=2000) as blocker:
            ctrl.capture_full()
    assert blocker.args[1] == "fullscreen"
