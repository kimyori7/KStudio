"""PreviewOverlay — 사각형 그리기 + 본체 이동 + 모서리 리사이즈 (선택 게이트)."""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QMouseEvent

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.rect import RectEffect, Point
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


def _rect_sidecar(eff: RectEffect) -> Sidecar:
    return Sidecar(source_path="x", source_hash="h",
                   trim=Trim(in_ms=0, out_ms=10_000), effects=[eff])


def _render_rect(ov: PreviewOverlay, w=640, h=360) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    ov.resize(w, h)
    ov._overlay_hits = []
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    if ov._sidecar is not None:
        for eff in ov._sidecar.effects:
            if eff.type == "rect" and eff.in_ms <= ov._position_ms < eff.out_ms:
                ov._draw_rect_effect(p, eff)
    p.end()
    return img


def _make_rect() -> RectEffect:
    # start=(0.3,0.4)→(192,144); end=(0.7,0.6)→(448,216) on 640x360.
    return RectEffect(in_ms=0, out_ms=10_000,
                      start=Point(x=0.3, y=0.4), end=Point(x=0.7, y=0.6),
                      color="#ff4040", thickness=4)


def _is_red(c: QColor) -> bool:
    return c.alpha() > 100 and c.red() > 150 and c.green() < 120 and c.blue() < 120


def _is_handle(c: QColor) -> bool:
    # 흰 채움 핸들 (240,240,240,240).
    return c.alpha() > 150 and c.red() > 200 and c.green() > 200 and c.blue() > 200


def test_rect_outline_drawn_in_window(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.set_sidecar(_rect_sidecar(_make_rect()))
    ov.set_position_ms(5000)
    img = _render_rect(ov)
    # 위 테두리 (y~144) 가운데에 빨간 픽셀.
    found = any(_is_red(QColor.fromRgba(img.pixel(320, y))) for y in range(140, 149))
    assert found


def test_corner_handles_gated_on_selection(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.set_sidecar(_rect_sidecar(_make_rect()))
    ov.set_position_ms(5000)
    # 선택 안 됨 → br 모서리(448,216) 근처에 흰 핸들 없음.
    img = _render_rect(ov)
    none_sel = any(_is_handle(QColor.fromRgba(img.pixel(x, y)))
                   for x in range(442, 455) for y in range(210, 223))
    assert not none_sel
    # 선택됨 → 흰 핸들 보임.
    eff = ov._sidecar.effects[0]
    ov.set_selected_effect_id(eff.id)
    img2 = _render_rect(ov)
    sel = any(_is_handle(QColor.fromRgba(img2.pixel(x, y)))
              for x in range(442, 455) for y in range(210, 223))
    assert sel


def test_body_drag_moves_both_corners(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)
    eff = _make_rect()
    ov.set_sidecar(_rect_sidecar(eff))
    ov.set_position_ms(5000)
    _render_rect(ov)
    # 본체 중앙 (320,180) → (340,200) 이동 (+20,+20).
    start, end = QPoint(320, 180), QPoint(340, 200)
    press = QMouseEvent(QMouseEvent.MouseButtonPress, start, ov.mapToGlobal(start),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QMouseEvent.MouseMove, end, ov.mapToGlobal(end),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.MouseButtonRelease, end, ov.mapToGlobal(end),
                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    with qtbot.waitSignal(ov.effect_drag_changed, timeout=500) as blocker:
        ov.mousePressEvent(press)
        ov.mouseMoveEvent(move)
        ov.mouseReleaseEvent(release)
    new_eff = blocker.args[0]
    assert isinstance(new_eff, RectEffect)
    # 두 모서리 같은 양만큼 이동 (+0.03125 x, +0.0556 y).
    assert abs(new_eff.start.x - (0.3 + 20/640)) < 0.01
    assert abs(new_eff.end.x - (0.7 + 20/640)) < 0.01
    assert abs(new_eff.start.y - (0.4 + 20/360)) < 0.01
    assert abs(new_eff.end.y - (0.6 + 20/360)) < 0.01


def test_corner_drag_keeps_opposite_fixed(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)
    eff = _make_rect()
    ov.set_sidecar(_rect_sidecar(eff))
    ov.set_position_ms(5000)
    ov.set_selected_effect_id(eff.id)
    _render_rect(ov)
    # br 모서리 (448,216) 잡고 (480,240) 으로.
    start, end = QPoint(448, 216), QPoint(480, 240)
    press = QMouseEvent(QMouseEvent.MouseButtonPress, start, ov.mapToGlobal(start),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QMouseEvent.MouseMove, end, ov.mapToGlobal(end),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.MouseButtonRelease, end, ov.mapToGlobal(end),
                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    with qtbot.waitSignal(ov.effect_drag_changed, timeout=500) as blocker:
        ov.mousePressEvent(press)
        ov.mouseMoveEvent(move)
        ov.mouseReleaseEvent(release)
    new_eff = blocker.args[0]
    from screen_recorder.ui.video.rect_overlay_geometry import corner_points
    cp = corner_points(new_eff.start.x, new_eff.start.y, new_eff.end.x, new_eff.end.y)
    # 대각 반대편 tl 은 원래 (0.3,0.4) 고정.
    assert abs(cp["tl"][0] - 0.3) < 0.01
    assert abs(cp["tl"][1] - 0.4) < 0.01
    # br 은 끌린 위치 (480/640=0.75, 240/360=0.667).
    assert abs(cp["br"][0] - 0.75) < 0.01
    assert abs(cp["br"][1] - 0.667) < 0.01
