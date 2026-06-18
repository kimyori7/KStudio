"""화살표 선택 해제 — 끝점 핸들은 선택됐을 때만 그린다 (Phase: 2026-06-17).

문제: 끝점 핸들(원)이 시간창 안이면 항상 그려져 화살촉 꼭짓점을 가림. 빈 곳을
클릭해도 핸들이 안 사라짐. 수정: overlay 가 _selected_eff_id 를 추적하고 핸들을
선택 시에만 그림.
"""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QMouseEvent

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.arrow import ArrowEffect, Point
from screen_recorder.ui.video.preview_overlay import PreviewOverlay


def _arrow_sidecar(eff: ArrowEffect) -> Sidecar:
    return Sidecar(source_path="x", source_hash="h",
                   trim=Trim(in_ms=0, out_ms=10_000), effects=[eff])


def _render_arrow(ov: PreviewOverlay, w=640, h=360) -> QImage:
    """overlay 의 활성 화살표를 QImage 에 직접 렌더 (paintEvent 우회).

    _draw_arrow_effect 가 _overlay_hits 등록 + 핸들 그리기를 담당.
    """
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    ov.resize(w, h)
    ov._overlay_hits = []
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    if ov._sidecar is not None:
        for eff in ov._sidecar.effects:
            if eff.type == "arrow" and eff.in_ms <= ov._position_ms < eff.out_ms:
                ov._draw_arrow_effect(p, eff)
    p.end()
    return img


def _is_dark_handle(c: QColor) -> bool:
    return c.alpha() > 100 and c.red() < 100 and c.green() < 100 and c.blue() < 100


def _make_arrow() -> ArrowEffect:
    # start=(0.3,0.5) → (192,180) on 640x360; end=(0.7,0.5) → (448,180).
    return ArrowEffect(in_ms=0, out_ms=10_000,
                       start=Point(x=0.3, y=0.5), end=Point(x=0.7, y=0.5))


def test_handles_hidden_when_not_selected(qtbot):
    """선택 안 됨 → 시작 끝점에 검은 핸들 원이 없다 (빨간 선만)."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = _make_arrow()
    ov.set_sidecar(_arrow_sidecar(eff))
    ov.set_position_ms(5000)
    # 선택 상태 없음 (기본).
    img = _render_arrow(ov)
    # 시작 끝점 (192,180) 중심에 검은 핸들 원이 없어야 함.
    c = QColor.fromRgba(img.pixel(192, 180))
    assert not _is_dark_handle(c), f"핸들이 그려지면 안 됨, got {c.red()},{c.green()},{c.blue()},{c.alpha()}"


def test_handles_shown_when_selected(qtbot):
    """선택됨 → 시작 끝점에 검은 핸들 원이 보인다."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    eff = _make_arrow()
    ov.set_sidecar(_arrow_sidecar(eff))
    ov.set_position_ms(5000)
    ov.set_selected_effect_id(eff.id)
    img = _render_arrow(ov)
    # 시작 끝점 (192,180) 근처에 검은 핸들 픽셀 존재.
    found = any(
        _is_dark_handle(QColor.fromRgba(img.pixel(x, y)))
        for x in range(186, 199) for y in range(174, 187)
    )
    assert found, "선택됐는데 핸들이 안 보임"


def test_set_selected_effect_id_setter(qtbot):
    """공개 setter 가 내부 상태를 갱신한다."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.set_selected_effect_id("abc")
    assert ov._selected_eff_id == "abc"
    ov.set_selected_effect_id(None)
    assert ov._selected_eff_id is None


def test_press_on_arrow_selects(qtbot):
    """화살표 본체 클릭 → _selected_eff_id 가 그 화살표로 설정."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)
    eff = _make_arrow()
    ov.set_sidecar(_arrow_sidecar(eff))
    ov.set_position_ms(5000)
    _render_arrow(ov)   # _overlay_hits 등록.
    # 화살표 본체 중간 (320,180) 클릭.
    pos = QPoint(320, 180)
    press = QMouseEvent(QMouseEvent.MouseButtonPress, pos, ov.mapToGlobal(pos),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ov.mousePressEvent(press)
    assert ov._selected_eff_id == eff.id


def test_press_empty_deselects(qtbot):
    """빈 영역 클릭 → _selected_eff_id 가 None 으로."""
    ov = PreviewOverlay()
    qtbot.addWidget(ov)
    ov.resize(640, 360)
    ov.show()
    qtbot.waitExposed(ov)
    eff = _make_arrow()
    ov.set_sidecar(_arrow_sidecar(eff))
    ov.set_position_ms(5000)
    ov.set_selected_effect_id(eff.id)
    _render_arrow(ov)
    # 화살표에서 멀리 떨어진 빈 곳 (50, 320) 클릭.
    pos = QPoint(50, 320)
    press = QMouseEvent(QMouseEvent.MouseButtonPress, pos, ov.mapToGlobal(pos),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ov.mousePressEvent(press)
    assert ov._selected_eff_id is None
