from PySide6.QtGui import QImage, QColor

from screen_recorder.ui.annotation.canvas import AnnotationCanvas


def _img(w=400, h=200) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(180, 180, 180))
    return img


def test_canvas_creates_scene_with_background(qtbot):
    c = AnnotationCanvas(_img(300, 200))
    qtbot.addWidget(c)
    assert c.scene().background_image().width() == 300


def test_canvas_fit_mode_scales_to_viewport(qtbot):
    c = AnnotationCanvas(_img(1000, 500))
    qtbot.addWidget(c)
    c.resize(400, 300)
    c.set_fit_mode()
    # transform m11 < 1 when image bigger than viewport
    assert c.transform().m11() < 1.0


def test_canvas_hundred_percent_mode(qtbot):
    c = AnnotationCanvas(_img(800, 400))
    qtbot.addWidget(c)
    c.set_hundred_percent_mode()
    assert abs(c.transform().m11() - 1.0) < 1e-6


def test_canvas_zoom_level_clamps(qtbot):
    c = AnnotationCanvas(_img(400, 200))
    qtbot.addWidget(c)
    c.set_zoom_factor(10.0)  # 400% 상한
    assert c.transform().m11() <= 4.0 + 1e-6
    c.set_zoom_factor(0.01)  # 25% 하한
    assert c.transform().m11() >= 0.25 - 1e-6


def test_canvas_render_composite_matches_bg_size(qtbot):
    c = AnnotationCanvas(_img(300, 150))
    qtbot.addWidget(c)
    img = c.render_composite()
    assert img.width() == 300
    assert img.height() == 150
