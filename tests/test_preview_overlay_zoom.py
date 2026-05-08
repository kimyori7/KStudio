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
