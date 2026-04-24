from unittest.mock import MagicMock, patch
from PySide6.QtCore import QPoint
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

    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=fake_img):
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


def test_main_window_is_hidden_then_restored(qtbot):
    main = MagicMock()
    main.isMinimized.return_value = False
    main.isVisible.return_value = True
    ctrl = ScreenshotController(main_window=main, viewer_getter=lambda: None)

    with patch("screen_recorder.screenshot.controller.snapshot_virtual_desktop", return_value=_fake_image()):
        with qtbot.waitSignal(ctrl.captured, timeout=2000):
            ctrl.capture_full()

    main.hide.assert_called()
    # 복원 — showNormal 이든 show 든 한 번은 호출되어야 함
    assert main.showNormal.called or main.show.called
