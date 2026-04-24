from screen_recorder.ui.overlay.region_selector import RegionSelector


def test_region_selector_instantiates_without_crash(qtbot):
    w = RegionSelector(show_magnifier=False)  # 단위 테스트에선 magnifier 비활성화
    qtbot.addWidget(w)
    # bounds 가 0x0 아님 (최소 화면 하나는 있어야 pytest-qt 가 동작)
    assert w.width() > 0
    assert w.height() > 0


def test_region_selector_can_accept_source_image(qtbot):
    from PySide6.QtGui import QImage
    w = RegionSelector(show_magnifier=True)
    qtbot.addWidget(w)
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(0)
    w.set_source_image(img)  # 안 깨지면 통과
