"""ArrowEffect — 데이터 모델 + 사이드카 round-trip + renderer / export PNG."""
from __future__ import annotations

import pytest

from screen_recorder.effects.sidecar import Sidecar
from screen_recorder.effects.types.arrow import ArrowEffect, Point, Fade


def test_arrow_effect_defaults():
    a = ArrowEffect(in_ms=0, out_ms=2000)
    assert a.type == "arrow"
    assert a.start.x == 0.3 and a.start.y == 0.5
    assert a.end.x == 0.7 and a.end.y == 0.5
    assert a.color == "#ff4040"
    assert a.thickness == 6
    assert a.fade.in_ms == 300


def test_arrow_thickness_validation():
    with pytest.raises(ValueError):
        ArrowEffect(in_ms=0, out_ms=2000, thickness=0)
    with pytest.raises(ValueError):
        ArrowEffect(in_ms=0, out_ms=2000, thickness=65)


def test_arrow_head_scale_default():
    a = ArrowEffect(in_ms=0, out_ms=2000)
    assert a.head_scale == 1.0


def test_arrow_head_scale_validation():
    with pytest.raises(ValueError):
        ArrowEffect(in_ms=0, out_ms=2000, head_scale=0.0)
    with pytest.raises(ValueError):
        ArrowEffect(in_ms=0, out_ms=2000, head_scale=9.0)


def test_arrow_head_scale_roundtrip():
    a = ArrowEffect(in_ms=0, out_ms=2000, head_scale=2.5)
    sc = Sidecar(effects=[a])
    a2 = Sidecar.from_dict(sc.to_dict()).effects[0]
    assert a2.head_scale == 2.5


def test_arrow_renderer_head_scale_enlarges_head():
    """head_scale 가 크면 화살촉이 더 커져 색칠 픽셀이 더 많다."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from screen_recorder.ui.video.arrow_renderer import draw_arrow

    def _ink(scale: float) -> int:
        a = ArrowEffect(in_ms=0, out_ms=2000,
                        start=Point(x=0.2, y=0.5), end=Point(x=0.8, y=0.5),
                        thickness=6, head_scale=scale)
        img = QImage(200, 100, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        try:
            draw_arrow(p, a, position_ms=1000, surface_w=200, surface_h=100)
        finally:
            p.end()
        return sum(1 for x in range(200) for y in range(100)
                   if QColor.fromRgba(img.pixel(x, y)).alpha() > 30)

    assert _ink(3.0) > _ink(1.0)


def test_arrow_roundtrip_sidecar():
    """사이드카 dict round-trip 시 Point / Fade 가 ArrowEffect 의 것으로 복원되어야.

    회귀 보호: _coerce_nested 가 parent_cls 별 매핑 안 하면 start/end 가 ZoomPoint
    (cx/cy/scale) 로 잘못 변환됨.
    """
    arr = ArrowEffect(
        in_ms=1000, out_ms=4000,
        start=Point(x=0.2, y=0.3),
        end=Point(x=0.8, y=0.7),
        color="#00ff00",
        thickness=10,
        fade=Fade(in_ms=100, out_ms=200),
    )
    sc = Sidecar(effects=[arr])
    d = sc.to_dict()
    sc2 = Sidecar.from_dict(d)
    assert len(sc2.effects) == 1
    a2 = sc2.effects[0]
    assert isinstance(a2, ArrowEffect)
    assert isinstance(a2.start, Point) and isinstance(a2.end, Point)
    assert a2.start.x == 0.2 and a2.start.y == 0.3
    assert a2.end.x == 0.8 and a2.end.y == 0.7
    assert a2.color == "#00ff00"
    assert a2.thickness == 10
    assert a2.fade.in_ms == 100


def test_arrow_renderer_fade_alpha():
    """캡션 fade 와 동일 공식 — in 진행 0% 부터 fade_in 동안 0→1, 끝 fade_out 동안 1→0."""
    from screen_recorder.ui.video.arrow_renderer import fade_alpha
    a = ArrowEffect(in_ms=1000, out_ms=4000, fade=Fade(in_ms=300, out_ms=300))
    assert fade_alpha(a, 999) == 0.0      # 범위 밖
    assert fade_alpha(a, 4000) == 0.0     # 범위 밖
    assert fade_alpha(a, 1000) == 0.0     # 시작점 (t=0 이라 ratio=0)
    assert abs(fade_alpha(a, 1150) - 0.5) < 0.01  # fade_in 절반
    assert fade_alpha(a, 2500) == 1.0     # 중간
    assert abs(fade_alpha(a, 3850) - 0.5) < 0.01  # fade_out 절반


def test_arrow_renderer_outside_window_no_op():
    """범위 밖 시점에 draw_arrow 호출해도 painter 가 깨끗 (return early)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from screen_recorder.ui.video.arrow_renderer import draw_arrow
    a = ArrowEffect(in_ms=0, out_ms=2000)
    img = QImage(100, 100, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    try:
        draw_arrow(p, a, position_ms=5000, surface_w=100, surface_h=100)
    finally:
        p.end()


def test_arrow_export_pipeline_includes_arrow_png(tmp_path, monkeypatch):
    """ArrowEffect 가 사이드카에 있으면 export argv 에 arrow_<id>.png 입력 + overlay 추가."""
    from screen_recorder.encode import export_pipeline as ep
    from screen_recorder.encode.export_pipeline import build_export_args
    # Qt 렌더 hang 회피 stub.
    def stub_caption(c, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
    def stub_speed_hud(eff, *, font_pt, dst):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
        return (100, 30)
    def stub_arrow(a, *, surface_w, surface_h, dst, sample_ms=None):
        from pathlib import Path
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"")
    monkeypatch.setattr(ep, "render_caption_png", stub_caption)
    monkeypatch.setattr(ep, "render_speed_hud_png", stub_speed_hud)
    monkeypatch.setattr(ep, "render_arrow_png", stub_arrow)

    arr = ArrowEffect(in_ms=1000, out_ms=3000)
    sc = Sidecar(effects=[arr])
    argv, pngs = build_export_args(
        sidecar=sc, src_path="A.mp4", dst_path=str(tmp_path / "out.mp4"),
        main_duration_ms=10000, surface_w=1920, surface_h=1080,
        ffmpeg_path="ffmpeg", png_dir=tmp_path,
    )
    # arrow PNG 입력 + overlay 둘 다.
    assert any(a.endswith(".png") and "arrow_" in a for a in argv)
    fc = next(argv[i + 1] for i, x in enumerate(argv) if x == "-filter_complex")
    assert "[arr0]" in fc
    # caller cleanup 위해 반환 png 리스트에도 포함.
    assert any("arrow_" in str(p) for p in pngs)
