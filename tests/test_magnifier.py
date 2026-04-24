from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QColor, QPainter

from screen_recorder.ui.overlay.magnifier import Magnifier


def test_magnifier_default_size(qtbot):
    m = Magnifier()
    qtbot.addWidget(m)
    # 120x120 확대 + 좌표 라벨 공간
    assert m.width() >= 120
    assert m.height() >= 120


def test_magnifier_set_source_and_update_at_does_not_crash(qtbot):
    src = QImage(400, 400, QImage.Format_ARGB32)
    src.fill(QColor(50, 200, 50))

    m = Magnifier()
    qtbot.addWidget(m)
    m.set_source(src)
    m.update_at(QPoint(100, 100))
    # 위젯이 repaint 호출을 받을 수 있도록 표시
    m.show()
    qtbot.waitExposed(m)


def test_magnifier_coord_text_reflects_last_update(qtbot):
    m = Magnifier()
    qtbot.addWidget(m)
    m.update_at(QPoint(1024, 768))
    assert "1024" in m.coord_text()
    assert "768" in m.coord_text()
