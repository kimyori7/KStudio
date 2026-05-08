"""PreviewOverlay — 영상 위 broll PiP 가이드 사각형 그리기 (canvas 단위 테스트).

Stage 7 v1: 실제 영상 PiP 는 적용하지 않고 모서리에 주황 사각형 + 🎞 라벨로 표시.
placement='fullscreen' 은 v1 미리보기 미지원 — 가이드 미표시.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


def _render_to_image(overlay: PreviewOverlay, w=640, h=360) -> QImage:
    """오버레이의 _draw_broll_guide 를 QImage 에 직접 렌더링.

    test_preview_overlay_zoom 와 같은 패턴 — paintEvent 를 직접 부르면 self 에
    QPainter 를 만들어야 해 실패. overlay 의 활성 BrollEffect 만 골라 직접 호출.
    """
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    overlay.resize(w, h)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    if overlay._sidecar is not None:
        for eff in overlay._sidecar.effects:
            if not isinstance(eff, BrollEffect):
                continue
            if not (eff.in_ms <= overlay._position_ms < eff.out_ms):
                continue
            if eff.placement != "pip" or eff.pip is None:
                continue
            overlay._draw_broll_guide(p, eff)
    p.end()
    return img


def _broll_sidecar(eff: BrollEffect) -> Sidecar:
    return Sidecar(source_path="x", source_hash="h",
                   trim=Trim(in_ms=0, out_ms=10_000), effects=[eff])


def _has_orange_pixel(img: QImage, *, region=None) -> bool:
    """이미지의 region (x1, y1, x2, y2) 에 주황(R 큼, G 중간, B 작음, alpha>0) 픽셀이 있는지.

    region=None 이면 전체 이미지 검사.
    """
    if region is None:
        x1, y1, x2, y2 = 0, 0, img.width(), img.height()
    else:
        x1, y1, x2, y2 = region
    for x in range(x1, x2, 2):
        for y in range(y1, y2, 2):
            c = QColor.fromRgba(img.pixel(x, y))
            # _BROLL_GUIDE_COLOR = (245, 158, 11, 220) — R 가 매우 크고 G 중간 B 작음.
            if c.alpha() > 0 and c.red() > 200 and 100 < c.green() < 200 and c.blue() < 60:
                return True
    return False


def test_pip_guide_drawn_in_active_window(qtbot):
    """활성 BrollEffect(PiP, 우하단) — 우하단 영역에서 주황 픽셀 검출."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = BrollEffect(
        in_ms=2000, out_ms=4000, src="myclip.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=640, h=360)
    # 우하단 영역만 검사 — 사각형이 가운데에 잘못 그려지면 실패.
    # 우하단: x=[640*0.6, 640], y=[360*0.6, 360]
    region = (int(640 * 0.6), int(360 * 0.6), 640, 360)
    assert _has_orange_pixel(img, region=region)


def test_pip_guide_top_left_corner(qtbot):
    """top-left 모서리 — 좌상단 영역에서 주황 픽셀 검출."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = BrollEffect(
        in_ms=2000, out_ms=4000, src="x.mp4",
        placement="pip",
        pip=PipConfig(corner="top-left", size_ratio=0.3),
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=640, h=360)
    # 좌상단 영역.
    region = (0, 0, int(640 * 0.4), int(360 * 0.4))
    assert _has_orange_pixel(img, region=region)


def test_pip_guide_outside_window_not_drawn(qtbot):
    """BrollEffect 의 시간 범위 밖 — 사각형 미표시 (거의 전부 투명)."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = BrollEffect(
        in_ms=2000, out_ms=4000, src="x.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(5000)   # 범위 밖
    img = _render_to_image(ov, w=640, h=360)
    # 거의 전부 투명.
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_fullscreen_placement_no_guide_drawn(qtbot):
    """placement='fullscreen' 이면 v1 에서 가이드 미표시 (BrollEffect.pip=None)."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = BrollEffect(
        in_ms=2000, out_ms=4000, src="x.mp4",
        placement="fullscreen", pip=None,
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=640, h=360)
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_no_broll_no_drawing(qtbot):
    """효과 0 개 — 가이드 미표시."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    sc = Sidecar(source_path="x", source_hash="h",
                 trim=Trim(in_ms=0, out_ms=10_000), effects=[])
    ov.set_sidecar(sc)
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=640, h=360)
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_pip_pos_x_y_overrides_corner(qtbot):
    """pip.pos_x / pos_y 가 둘 다 set 이면 corner 무시하고 자유 위치에 그린다."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = BrollEffect(
        in_ms=0, out_ms=10_000, src="x.mp4",
        placement="pip",
        # corner 는 우하단이지만 pos 는 정 가운데(0.4, 0.4) — 가운데에서 주황 발견.
        pip=PipConfig(corner="bottom-right", size_ratio=0.2, pos_x=0.4, pos_y=0.4),
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=640, h=360)
    # 가운데 영역에서 주황 검출.
    region = (int(640 * 0.35), int(360 * 0.35), int(640 * 0.7), int(360 * 0.7))
    assert _has_orange_pixel(img, region=region)


def test_pip_drag_emits_pos_x_y_and_keeps_corner(qtbot):
    """곁들임 PiP 사각형 드래그 → pip.pos_x / pos_y 갱신 + effect_drag_changed.

    corner 값은 초기 기본 (bottom-right) 그대로 — pos_x/y 가 우선되므로 의미 없어짐.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)

    eff = BrollEffect(
        in_ms=0, out_ms=10_000, src="x.mp4",
        placement="pip",
        pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    ov.set_sidecar(_broll_sidecar(eff))
    ov.set_position_ms(3000)

    # paintEvent 로 bbox 등록을 한 번 시뮬레이션.
    img = _render_to_image(ov, w=640, h=360)
    # 우하단 PiP 박스 영역의 한 점에서 드래그 시작.
    # corner='bottom-right' size_ratio=0.3 → 박스 = (640-192-8, 360-108-8, 192, 108)
    # = (440, 244, 192, 108). 박스 안의 한 점 (500, 280) 에서 (250, 130) 으로 드래그.
    start = QPoint(500, 280)
    end = QPoint(250, 130)
    press = QMouseEvent(QMouseEvent.MouseButtonPress, start,
                         ov.mapToGlobal(start), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    move = QMouseEvent(QMouseEvent.MouseMove, end,
                        ov.mapToGlobal(end), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.MouseButtonRelease, end,
                           ov.mapToGlobal(end), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)

    with qtbot.waitSignal(ov.effect_drag_changed, timeout=500) as blocker:
        ov.mousePressEvent(press)
        ov.mouseMoveEvent(move)
        ov.mouseReleaseEvent(release)
    new_eff = blocker.args[0]
    assert isinstance(new_eff, BrollEffect)
    assert new_eff.id == eff.id
    assert new_eff.pip is not None
    assert new_eff.pip.pos_x is not None and new_eff.pip.pos_y is not None
    # 좌상단 쪽으로 옮겼으므로 pos_x/y 모두 작아야 함.
    assert 0.0 <= new_eff.pip.pos_x < 0.5
    assert 0.0 <= new_eff.pip.pos_y < 0.5
    # corner 와 size_ratio 는 그대로 유지.
    assert new_eff.pip.corner == "bottom-right"
    assert abs(new_eff.pip.size_ratio - 0.3) < 1e-6
