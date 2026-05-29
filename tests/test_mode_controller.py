from screen_recorder.ui.mode_controller import ModeController, AppMode


def test_initial_mode_is_image(qtbot):
    mc = ModeController()
    assert mc.mode() is AppMode.IMAGE


def test_setting_mode_emits_signal(qtbot):
    mc = ModeController()
    with qtbot.waitSignal(mc.mode_changed, timeout=200) as blocker:
        mc.set_mode(AppMode.VIDEO)
    assert blocker.args == [AppMode.VIDEO]


def test_setting_same_mode_does_not_emit(qtbot):
    mc = ModeController()
    mc.set_mode(AppMode.VIDEO)
    with qtbot.assertNotEmitted(mc.mode_changed, wait=200):
        mc.set_mode(AppMode.VIDEO)


def test_document_mode_set_and_get(qtbot):
    mc = ModeController(initial_mode=AppMode.IMAGE)
    received = []
    mc.mode_changed.connect(received.append)
    mc.set_mode(AppMode.DOCUMENT)
    assert mc.mode() is AppMode.DOCUMENT
    assert received == [AppMode.DOCUMENT]
    assert AppMode.DOCUMENT.value == "document"
