"""PreviewOverlay — 영상 위 캡션 그리기 (canvas 단위 테스트)."""
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QColor

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.caption import CaptionEffect, Position
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


def _render_to_image(overlay: PreviewOverlay, w=640, h=360) -> QImage:
    """오버레이의 paintEvent 를 QImage 에 직접 렌더링 (배경 투명 유지)."""
    from PySide6.QtGui import QPaintEvent
    from PySide6.QtCore import QRect
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    overlay.resize(w, h)
    p = QPainter(img)
    # paintEvent 를 직접 호출 — WA_TranslucentBackground 는 화면 합성에서만
    # 작동하므로 오프스크린 렌더는 paintEvent 를 직접 호출하는 것이 올바름.
    event = QPaintEvent(QRect(0, 0, w, h))
    # painter 없이 paintEvent 만 호출하면 self 에 QPainter 를 생성하려 해서 실패.
    # 대신 overlay 의 paint 로직을 painter 에 직접 그린다.
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    if overlay._sidecar is not None:
        for eff in overlay._sidecar.effects:
            if eff.type == "caption":
                overlay._draw_caption(p, eff)
    p.end()
    return img


def test_no_caption_at_position_renders_blank(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=2000, out_ms=4000, text="hi")])
    ov.set_sidecar(sc)
    ov.set_position_ms(0)   # 캡션 시간 외
    img = _render_to_image(ov)
    # 거의 전부 투명 — alpha 합이 0 에 가까움
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_caption_in_window_renders_text(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=2000, out_ms=4000, text="HELLO",
                                         position=Position(anchor="middle-center"))])
    ov.set_sidecar(sc)
    ov.set_position_ms(3000)
    img = _render_to_image(ov)
    # 텍스트가 그려졌으면 어딘가 alpha > 0 픽셀 존재
    has_visible = any(QColor.fromRgba(img.pixel(x, y)).alpha() > 50
                       for x in range(0, img.width(), 10)
                       for y in range(img.height() // 3, 2 * img.height() // 3, 10))
    assert has_visible is True


def test_caption_outside_window_not_rendered(qtbot):
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[CaptionEffect(in_ms=2000, out_ms=4000, text="HELLO")])
    ov.set_sidecar(sc)
    ov.set_position_ms(7000)   # 캡션 시간 외
    img = _render_to_image(ov)
    # 거의 투명
    pixels = [QColor.fromRgba(img.pixel(x, y)).alpha()
              for x in range(0, img.width(), 40) for y in range(0, img.height(), 40)]
    assert max(pixels) <= 5


def test_fade_alpha_at_start(qtbot):
    """fade.in_ms=400, position=in_ms+100 → alpha 약 25%."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    from screen_recorder.effects.types.caption import Fade
    eff = CaptionEffect(in_ms=2000, out_ms=4000, text="X",
                         fade=Fade(in_ms=400, out_ms=400),
                         position=Position(anchor="middle-center"))
    sc = Sidecar(source_path="x", source_hash="h", trim=Trim(in_ms=0, out_ms=10_000),
                 effects=[eff])
    ov.set_sidecar(sc)
    ov.set_position_ms(2100)   # in 후 100ms — fade-in 25%
    img = _render_to_image(ov)
    # alpha 가 0보다 크지만 max(255) 보다는 작아야.
    # 단일 문자 "X" 는 좁아 step=5 로 놓치기 쉬우므로 step=1 로 전체 스캔.
    max_alpha = max(QColor.fromRgba(img.pixel(x, y)).alpha()
                    for x in range(0, img.width())
                    for y in range(0, img.height()))
    assert 0 < max_alpha < 255
