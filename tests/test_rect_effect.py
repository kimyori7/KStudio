"""RectEffect — 데이터 모델 + 사이드카 round-trip + renderer (테두리 사각형).

ArrowEffect 패턴 답습. 차이: 화살촉 없음, 두 점은 대각 모서리, 테두리만(채움 X).
"""
from __future__ import annotations

import pytest

from screen_recorder.effects.sidecar import Sidecar
from screen_recorder.effects.types.rect import RectEffect, Point, Fade


def test_rect_effect_defaults():
    r = RectEffect(in_ms=0, out_ms=2000)
    assert r.type == "rect"
    assert r.start.x == 0.3 and r.start.y == 0.4
    assert r.end.x == 0.7 and r.end.y == 0.6
    assert r.color == "#ff4040"
    assert r.thickness == 4
    assert r.fade.in_ms == 300
    assert r.fade.out_ms == 300


def test_rect_thickness_validation():
    with pytest.raises(ValueError):
        RectEffect(in_ms=0, out_ms=2000, thickness=0)
    with pytest.raises(ValueError):
        RectEffect(in_ms=0, out_ms=2000, thickness=65)


def test_rect_point_validation():
    with pytest.raises(ValueError):
        RectEffect(in_ms=0, out_ms=2000, start=Point(x=2.0, y=0.5))


def test_rect_roundtrip_sidecar():
    """round-trip 시 start/end/fade 가 RectEffect 의 Point/Fade 로 복원돼야.

    회귀 보호: _coerce_nested 가 parent_cls 별 매핑 안 하면 ZoomPoint/CapFade 로 오변환.
    """
    rect = RectEffect(
        in_ms=1000, out_ms=4000,
        start=Point(x=0.2, y=0.3),
        end=Point(x=0.8, y=0.7),
        color="#00ff00",
        thickness=10,
        fade=Fade(in_ms=100, out_ms=200),
    )
    sc = Sidecar(effects=[rect])
    d = sc.to_dict()
    sc2 = Sidecar.from_dict(d)
    assert len(sc2.effects) == 1
    r2 = sc2.effects[0]
    assert isinstance(r2, RectEffect)
    assert isinstance(r2.start, Point) and isinstance(r2.end, Point)
    assert isinstance(r2.fade, Fade)
    assert r2.start.x == 0.2 and r2.start.y == 0.3
    assert r2.end.x == 0.8 and r2.end.y == 0.7
    assert r2.color == "#00ff00"
    assert r2.thickness == 10
    assert r2.fade.in_ms == 100 and r2.fade.out_ms == 200


def test_rect_renderer_fade_alpha():
    from screen_recorder.ui.video.rect_renderer import fade_alpha
    r = RectEffect(in_ms=1000, out_ms=4000, fade=Fade(in_ms=300, out_ms=300))
    assert fade_alpha(r, 999) == 0.0
    assert fade_alpha(r, 4000) == 0.0
    assert fade_alpha(r, 1000) == 0.0
    assert abs(fade_alpha(r, 1150) - 0.5) < 0.01
    assert fade_alpha(r, 2500) == 1.0
    assert abs(fade_alpha(r, 3850) - 0.5) < 0.01


def test_rect_renderer_outside_window_no_op():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from screen_recorder.ui.video.rect_renderer import draw_rect
    r = RectEffect(in_ms=0, out_ms=2000)
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    try:
        draw_rect(p, r, position_ms=5000, surface_w=100, surface_h=100)
    finally:
        p.end()


def test_rect_renderer_outline_only():
    """테두리만 — 테두리 픽셀은 색칠, 중앙은 투명(채움 없음)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from screen_recorder.ui.video.rect_renderer import draw_rect
    # (25,25)~(75,75) 사각형, 100x100 surface.
    r = RectEffect(in_ms=0, out_ms=2000, start=Point(x=0.25, y=0.25),
                   end=Point(x=0.75, y=0.75), color="#ff4040", thickness=4)
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    try:
        draw_rect(p, r, position_ms=1000, surface_w=100, surface_h=100)
    finally:
        p.end()
    # 중앙(50,50)은 투명 (채움 없음).
    center = QColor.fromRgba(img.pixel(50, 50))
    assert center.alpha() < 10, f"중앙이 채워지면 안 됨 alpha={center.alpha()}"
    # 위쪽 테두리(50,25 근처)에 빨간 픽셀 존재.
    found = any(
        (lambda c: c.alpha() > 100 and c.red() > 150 and c.green() < 120)(
            QColor.fromRgba(img.pixel(50, y)))
        for y in range(22, 29)
    )
    assert found, "테두리 픽셀이 안 그려짐"


def test_rect_renderer_no_box_inversion():
    """start/end 가 뒤집혀도(end 가 좌상단) min/max 로 정상 사각형이 그려진다."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from screen_recorder.ui.video.rect_renderer import draw_rect
    # 일부러 start 가 우하단, end 가 좌상단 (뒤집힘).
    r = RectEffect(in_ms=0, out_ms=2000, start=Point(x=0.75, y=0.75),
                   end=Point(x=0.25, y=0.25), color="#ff4040", thickness=4)
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    try:
        draw_rect(p, r, position_ms=1000, surface_w=100, surface_h=100)
    finally:
        p.end()
    # 동일하게 (25,25)~(75,75) 테두리가 그려져야 — 위 테두리 픽셀 존재.
    found = any(
        (lambda c: c.alpha() > 100 and c.red() > 150)(QColor.fromRgba(img.pixel(50, y)))
        for y in range(22, 29)
    )
    assert found, "뒤집힌 좌표에서 사각형이 안 그려짐(비반전 실패)"


def test_rect_export_pipeline_includes_rect_png(tmp_path, monkeypatch):
    """RectEffect 가 사이드카에 있으면 export argv 에 rect_<id>.png 입력 + overlay 추가."""
    from screen_recorder.encode import export_pipeline as ep
    from screen_recorder.encode.export_pipeline import build_export_args

    def stub_caption(c, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")

    def stub_speed_hud(eff, *, font_pt, dst):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
        return (100, 30)

    def stub_rect(r, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")

    monkeypatch.setattr(ep, "render_caption_png", stub_caption)
    monkeypatch.setattr(ep, "render_speed_hud_png", stub_speed_hud)
    monkeypatch.setattr(ep, "render_rect_png", stub_rect)

    rect = RectEffect(in_ms=1000, out_ms=3000)
    sc = Sidecar(effects=[rect])
    argv, pngs = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path=str(tmp_path / "out.mp4"),
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg", png_dir=tmp_path,
    )
    assert any(a.endswith(".png") and "rect_" in a for a in argv)
    fc = next(argv[i + 1] for i, x in enumerate(argv) if x == "-filter_complex")
    assert "[rect0]" in fc
    assert any("rect_" in str(p) for p in pngs)
