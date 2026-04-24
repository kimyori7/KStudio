from screen_recorder.ui.screenshot_close_dialog import CloseDialog, CloseAction


def test_action_enum_has_three_distinct_values():
    assert CloseAction.CLOSE_ALL != CloseAction.CLOSE_CURRENT
    assert CloseAction.CLOSE_ALL != CloseAction.CANCEL
    assert CloseAction.CLOSE_CURRENT != CloseAction.CANCEL


def test_dialog_default_result_is_cancel(qtbot):
    d = CloseDialog(unsaved_count=2, parent=None)
    qtbot.addWidget(d)
    # 다이얼로그를 exec 하지 않고 바로 result 를 읽으면 기본값이 CANCEL 이어야 함
    assert d.action() == CloseAction.CANCEL


def test_choose_close_all_sets_action(qtbot):
    d = CloseDialog(unsaved_count=3)
    qtbot.addWidget(d)
    d._choose(CloseAction.CLOSE_ALL)  # 내부 슬롯 직접 호출 (테스트 용)
    assert d.action() == CloseAction.CLOSE_ALL


def test_choose_close_current_sets_action(qtbot):
    d = CloseDialog(unsaved_count=1)
    qtbot.addWidget(d)
    d._choose(CloseAction.CLOSE_CURRENT)
    assert d.action() == CloseAction.CLOSE_CURRENT
