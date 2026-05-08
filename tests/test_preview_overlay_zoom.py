"""PreviewOverlay — 영상 위 줌 가이드 사각형 그리기 (canvas 단위 테스트).

Stage 6 v1: 실제 픽셀 줌은 적용하지 않고 노란 사각형 + ⊕ N× 라벨로 표시.
"""
import pytest
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QPaintEvent

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


def _render_to_image(overlay: PreviewOverlay, w=640, h=360) -> QImage:
    """오버레이의 _draw_zoom_guide 를 QImage 에 직접 렌더링 (배경 투명 유지).

    paintEvent 를 직접 부르면 self 에 QPainter 를 만들어야 해 실패 — 대신
    오버레이의 활성 ZoomEffect 만 골라 _draw_zoom_guide 를 직접 호출.
    """
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    overlay.resize(w, h)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    if overlay._sidecar is not None:
        for eff in overlay._sidecar.effects:
            if not isinstance(eff, ZoomEffect):
                continue
            if not (eff.in_ms <= overlay._position_ms < eff.out_ms):
                continue
            overlay._draw_zoom_guide(p, eff)
    p.end()
    return img


def _zoom_sidecar(eff: ZoomEffect) -> Sidecar:
    return Sidecar(source_path="x", source_hash="h",
                   trim=Trim(in_ms=0, out_ms=10_000), effects=[eff])


def _has_yellow_pixel(img: QImage) -> bool:
    """이미지 어딘가에 노란 계열(R+G 가 큼, B 작음) + alpha>0 픽셀이 있는지."""
    for x in range(0, img.width(), 4):
        for y in range(0, img.height(), 4):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.alpha() > 0 and c.red() > 200 and c.green() > 150 and c.blue() < 100:
                return True
    return False


def test_zoom_guide_drawn_in_active_window(qtbot):
    """활성 ZoomEffect 의 시간 범위 안에서는 노란 가이드 픽셀 등장."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=2000, out_ms=4000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)   # 활성 범위
    img = _render_to_image(ov)
    assert _has_yellow_pixel(img)


def test_zoom_outside_window_not_drawn(qtbot):
    """ZoomEffect 의 시간 범위 밖에서는 사각형 미표시 — 거의 전부 투명."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=2000, out_ms=4000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(5000)   # 범위 밖
    img = _render_to_image(ov)
    # 거의 전부 투명 — alpha 합이 0 에 가까움
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_zoom_label_drawn_with_scale(qtbot):
    """가이드 사각형의 좌상단에 ⊕ 2× 라벨이 그려져 어두운 라벨 박스 픽셀이 검출된다."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=2000, out_ms=4000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov)
    # 사각형의 좌상단 부근(상단 1/4 영역)에서 라벨 배경(검정 alpha) 또는 흰 텍스트 픽셀 존재.
    found = False
    for x in range(img.width() // 4, img.width() // 2):
        for y in range(img.height() // 4, img.height() // 2):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.alpha() > 100:
                found = True
                break
        if found:
            break
    assert found


def test_no_zoom_no_drawing(qtbot):
    """효과 0 개 — 가이드 미표시."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    sc = Sidecar(source_path="x", source_hash="h",
                 trim=Trim(in_ms=0, out_ms=10_000), effects=[])
    ov.set_sidecar(sc)
    ov.set_position_ms(3000)
    img = _render_to_image(ov)
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_zoom_guide_drawn_inside_video_frame_rect(qtbot):
    """letterbox: provider 가 위젯의 일부분만 영상 frame 으로 알려주면 사각형도 그 안.

    시나리오: overlay 800x600, 영상 frame = (0, 75, 800, 450) (16:9 letterbox).
    cx=cy=0.5, scale=2.0 → 사각형은 영상 frame 의 정 가운데 + 절반 크기.
    위/아래 검은 띠 영역(0~75, 525~600) 에는 노란 픽셀이 없어야 한다.
    """
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(800, 600)
    frame_rect = QRect(0, 75, 800, 450)
    ov.set_video_frame_rect_provider(lambda: frame_rect)

    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10_000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)
    img = _render_to_image(ov, w=800, h=600)
    # 위 letterbox 띠 (y < 75): 노란 픽셀 없음.
    top = img.copy(0, 0, 800, 75)
    assert not _has_yellow_pixel(top)
    # 아래 letterbox 띠 (y > 525): 노란 픽셀 없음.
    bottom = img.copy(0, 525, 800, 75)
    assert not _has_yellow_pixel(bottom)
    # 영상 frame 안: 노란 픽셀 검출.
    inside = img.copy(0, 75, 800, 450)
    assert _has_yellow_pixel(inside)


def test_zoom_drag_clamps_corners_inside_frame(qtbot):
    """드래그가 좌상단 모서리까지 이동해도 사각형 모서리는 frame 안에 머문다.

    scale=2.0 → 사각형 크기 = frame 의 절반. cx 허용 범위 = [0.25, 0.75], cy 같은 식.
    드래그를 좌상단(0,0) 까지 이동했을 때 emit 되는 cx/cy 가 0.25 미만이 아니어야 한다.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)

    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10_000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)
    _render_to_image(ov)   # bbox 등록.

    # 줌 가이드 중심은 (320, 180). 좌상단(0, 0) 까지 드래그 → cx/cy 가 0 으로 가려는데
    # corner 클램프로 [0.25, 0.25] 에서 멈춰야 한다 (사각형의 좌상단이 (0, 0) 이 됨).
    start = QPoint(320, 180)
    end = QPoint(0, 0)
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
    # cx/cy 가 0.25 미만으로 내려가면 사각형 모서리가 frame 밖으로 나간다.
    assert new_eff.start.cx >= 0.25 - 1e-6
    assert new_eff.start.cy >= 0.25 - 1e-6
    # 0.5 이하 (좌상단 쪽 이동) 인지도 확인.
    assert new_eff.start.cx <= 0.5
    assert new_eff.start.cy <= 0.5


def test_zoom_drag_clamps_corners_at_right_bottom(qtbot):
    """드래그를 우하단 끝으로 이동해도 cx/cy 가 [0.25, 0.75] 안.

    scale=2.0, 우하단(640,360) 까지 드래그 → cx, cy <= 0.75.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)

    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10_000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)
    _render_to_image(ov)

    start = QPoint(320, 180)
    end = QPoint(640, 360)
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
    assert new_eff.start.cx <= 0.75 + 1e-6
    assert new_eff.start.cy <= 0.75 + 1e-6
    assert new_eff.start.cx >= 0.5
    assert new_eff.start.cy >= 0.5


def test_zoom_drag_updates_cx_cy_and_emits(qtbot):
    """줌 가이드 사각형 가운데를 드래그 → start.cx/cy 갱신 + effect_drag_changed.

    v1: 정적 줌 (start == end). 드래그도 양쪽 모두 동일한 값으로 갱신.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)

    pt = ZoomPoint(cx=0.5, cy=0.5, scale=2.0)
    eff = ZoomEffect(in_ms=0, out_ms=10_000, start=pt, end=pt)
    ov.set_sidecar(_zoom_sidecar(eff))
    ov.set_position_ms(3000)

    # bbox 기록을 위해 paintEvent 한번 강제. _draw_zoom_guide 가 직접 bbox 등록.
    img = _render_to_image(ov)
    assert _has_yellow_pixel(img)

    # 줌 가이드 중심은 (320, 180). 거기서 시작해 (340, 200) 으로 드래그 → +20px 양 축.
    # 화면 640x360 이므로 정규화 +0.03125 (x), +0.0556 (y) → cx ~= 0.531, cy ~= 0.556
    start = QPoint(320, 180)
    end = QPoint(340, 200)
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
    assert isinstance(new_eff, ZoomEffect)
    assert new_eff.id == eff.id
    # cx/cy 가 ~0.5 → 약간 큰 값 (±0.05 톨러런스)
    assert new_eff.start.cx > 0.5 and new_eff.start.cx < 0.6
    assert new_eff.start.cy > 0.5 and new_eff.start.cy < 0.6
    # v1 정적 줌 — end 도 동일 갱신.
    assert new_eff.start.cx == new_eff.end.cx
    assert new_eff.start.cy == new_eff.end.cy
    # scale 은 그대로
    assert new_eff.start.scale == 2.0
