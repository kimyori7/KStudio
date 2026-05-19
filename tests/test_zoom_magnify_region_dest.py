"""ZoomEffect.magnify_region — dest rect 분리 + 5px 규칙 검증."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QRect

from screen_recorder.effects.types.zoom import ZoomEffect, ZoomPoint


def _eff(**kw) -> ZoomEffect:
    defaults = dict(
        in_ms=0, out_ms=2000, mode="magnify_region",
        start=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
        end=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
        region_w=0.3, region_h=0.3,
        dest_cx=0.5, dest_cy=0.5, dest_w=0.6, dest_h=0.6,
    )
    defaults.update(kw)
    return ZoomEffect(**defaults)


_OVERLAYS: list = []


def _make_overlay():
    """qtbot 없이 PreviewOverlay 인스턴스 — qapp fixture 가 QApplication 보장."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    o = PreviewOverlay()
    _OVERLAYS.append(o)   # GC 방지
    return o


def test_zoom_effect_accepts_dest_fields():
    e = _eff(dest_cx=0.7, dest_cy=0.3, dest_w=0.5, dest_h=0.4)
    assert e.dest_cx == 0.7
    assert e.dest_cy == 0.3
    assert e.dest_w == 0.5
    assert e.dest_h == 0.4


def test_zoom_effect_rejects_out_of_range_dest():
    with pytest.raises(ValueError):
        _eff(dest_cx=1.5)
    with pytest.raises(ValueError):
        _eff(dest_w=3.0)
    with pytest.raises(ValueError):
        _eff(dest_h=0.01)


def test_export_filter_uses_dest_rect():
    """export_pipeline 의 zoom filter 가 dest_w/h/cx/cy 를 반영해야 한다."""
    from screen_recorder.encode.export_pipeline import _zoom_crop_scale_filter
    e = _eff(
        start=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
        end=ZoomPoint(cx=0.5, cy=0.5, scale=2.0),
        region_w=0.2, region_h=0.2,
        dest_cx=0.8, dest_cy=0.2, dest_w=0.4, dest_h=0.3,
    )
    f = _zoom_crop_scale_filter(e, 1000, 500)
    # source crop = 200×100 around (500, 250) → x=400, y=200.
    assert "crop=200:100:400:200" in f
    # dest scale = 400×150 (0.4 × 1000, 0.3 × 500).
    assert "scale=400:150" in f
    # dest overlay = around (800, 100), w 400, h 150 → x=600, y=25.
    assert "overlay=x=600:y=25" in f


def test_dest_can_be_smaller_than_src(qtbot):
    """Phase 28 — 5px 규칙 제거. dest 가 src 보다 작아도 그대로 보존 (자유 배치)."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    overlay = PreviewOverlay()
    qtbot.addWidget(overlay)
    overlay._frame_rect_provider = lambda: QRect(0, 0, 1000, 500)
    # src = 0.3 × 0.3, dest 를 0.1 × 0.1 (더 작게) — 자유 배치 허용.
    e = _eff(region_w=0.3, region_h=0.3, dest_w=0.1, dest_h=0.1)
    new_eff = overlay._apply_resize_to_effect("zoom-dst", e, (0.5, 0.5, 0.1, 0.1))
    assert new_eff.dest_w == 0.1
    assert new_eff.dest_h == 0.1


def test_dest_can_be_anywhere(qtbot):
    """dest 가 src 와 완전히 분리된 위치도 허용."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    overlay = PreviewOverlay()
    qtbot.addWidget(overlay)
    overlay._frame_rect_provider = lambda: QRect(0, 0, 1000, 500)
    e = _eff(start=ZoomPoint(cx=0.3, cy=0.3, scale=2.0),
             end=ZoomPoint(cx=0.3, cy=0.3, scale=2.0),
             region_w=0.2, region_h=0.2)
    # dest 를 화면 우하단으로 — src 와 겹치지 않음.
    new_eff = overlay._apply_resize_to_effect("zoom-dst", e, (0.8, 0.8, 0.3, 0.3))
    assert new_eff.dest_cx == 0.8
    assert new_eff.dest_cy == 0.8


def test_handle_resize_zoom_src_changes_region(qtbot):
    """zoom-src 의 4-tuple resize override 가 region_w/h + cx/cy 에 반영."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    overlay = PreviewOverlay()
    qtbot.addWidget(overlay)
    overlay._frame_rect_provider = lambda: QRect(0, 0, 1000, 500)
    e = _eff()
    new_eff = overlay._apply_resize_to_effect("zoom-src", e, (0.3, 0.4, 0.5, 0.6))
    assert new_eff is not None
    assert new_eff.start.cx == 0.3
    assert new_eff.start.cy == 0.4
    assert new_eff.region_w == 0.5
    assert new_eff.region_h == 0.6


def test_handle_resize_zoom_dst_changes_dest(qtbot):
    """zoom-dst 의 4-tuple resize override 가 dest_w/h/cx/cy 에 반영 (충분히 큰 dest)."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    overlay = PreviewOverlay()
    qtbot.addWidget(overlay)
    overlay._frame_rect_provider = lambda: QRect(0, 0, 1000, 500)
    # source = (0.5, 0.5, 0.3, 0.3). dest 가 모든 변에서 ≥5px 큰 값으로.
    e = _eff()
    new_eff = overlay._apply_resize_to_effect("zoom-dst", e, (0.5, 0.5, 0.8, 0.7))
    assert new_eff is not None
    assert new_eff.dest_cx == 0.5
    assert new_eff.dest_cy == 0.5
    assert new_eff.dest_w == 0.8
    assert new_eff.dest_h == 0.7


def test_initial_resize_override_returns_4tuple_for_magnify(qtbot):
    """_initial_resize_override 가 zoom-src/zoom-dst 면 4-tuple."""
    from screen_recorder.ui.video.preview_overlay import PreviewOverlay
    from screen_recorder.effects import Sidecar
    overlay = PreviewOverlay()
    qtbot.addWidget(overlay)
    e = _eff(region_w=0.4, region_h=0.3, dest_w=0.7, dest_h=0.6,
             dest_cx=0.6, dest_cy=0.4)
    overlay.set_sidecar(Sidecar(effects=[e]))
    src = overlay._initial_resize_override("zoom-src", e.id)
    dst = overlay._initial_resize_override("zoom-dst", e.id)
    assert len(src) == 4 and src[2] == 0.4 and src[3] == 0.3
    assert len(dst) == 4 and dst == (0.6, 0.4, 0.7, 0.6)


def test_fit_screen_unaffected_by_dest_fields(qtbot):
    """Phase 28 — 5px 규칙 제거. fit_screen 모드는 dest 필드 자체가 무관 (그냥 보존)."""
    e = _eff(mode="fit_screen", dest_w=0.05, dest_h=0.05)
    # 변형 함수 호출 없이도 ZoomEffect 검증 통과해야 함.
    assert e.dest_w == 0.05
    assert e.dest_h == 0.05
