"""이미지 업/다운스케일 (scale.py + ScaleDialog) 테스트."""
from __future__ import annotations
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from screen_recorder.encode.scale import (
    scale_qimage, resolve_scaled_path, save_scaled,
)
from screen_recorder.ui.scale_dialog import ScaleDialog


def _solid_image(w: int, h: int, color: int = 0xFF8844AA) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(color)
    return img


# ---------- scale_qimage ----------

def test_scale_qimage_returns_target_size():
    src = _solid_image(100, 50)
    out = scale_qimage(src, 200, 100)
    assert out.width() == 200
    assert out.height() == 100


def test_scale_qimage_preserves_pixels_for_solid_color():
    src = _solid_image(100, 100, 0xFFAABBCC)
    out = scale_qimage(src, 50, 50)
    # 단색이면 LANCZOS 도 같은 색을 유지 (테두리 픽셀 완벽 일치는 보장 X 라
    # 중앙 픽셀만 비교).
    rgba = out.pixelColor(25, 25)
    assert rgba.red() == 0xAA
    assert rgba.green() == 0xBB
    assert rgba.blue() == 0xCC


def test_scale_qimage_rejects_nonpositive():
    src = _solid_image(10, 10)
    with pytest.raises(ValueError):
        scale_qimage(src, 0, 100)
    with pytest.raises(ValueError):
        scale_qimage(src, 100, -1)


def test_scale_qimage_does_not_mutate_input():
    src = _solid_image(40, 40)
    _ = scale_qimage(src, 80, 80)
    assert src.width() == 40 and src.height() == 40


# ---------- resolve_scaled_path ----------

def test_resolve_scaled_path_first_uses_001(tmp_path: Path):
    src = tmp_path / "shot.png"
    src.touch()
    out = resolve_scaled_path(src, 200, 100)
    assert out == tmp_path / "shot_scaled_200x100_001.png"


def test_resolve_scaled_path_increments_on_collision(tmp_path: Path):
    src = tmp_path / "shot.png"
    src.touch()
    (tmp_path / "shot_scaled_200x100_001.png").touch()
    (tmp_path / "shot_scaled_200x100_002.png").touch()
    out = resolve_scaled_path(src, 200, 100)
    assert out == tmp_path / "shot_scaled_200x100_003.png"


def test_resolve_scaled_path_always_png_regardless_of_source_ext(tmp_path: Path):
    src = tmp_path / "shot.jpg"
    src.touch()
    out = resolve_scaled_path(src, 50, 50)
    assert out.suffix == ".png"


# ---------- save_scaled ----------

def test_save_scaled_writes_file(tmp_path: Path):
    src = _solid_image(20, 20)
    dst = tmp_path / "out.png"
    save_scaled(src, dst)
    assert dst.exists()
    assert dst.stat().st_size > 0
    # 다시 읽어 사이즈 확인
    re = QImage(str(dst))
    assert re.width() == 20 and re.height() == 20


# ---------- ScaleDialog ----------

def test_dialog_default_target_equals_source(qtbot):
    dlg = ScaleDialog(src_w=800, src_h=400)
    qtbot.addWidget(dlg)
    assert dlg.target_size() == (800, 400)


def test_dialog_lock_aspect_updates_height_when_width_changes(qtbot):
    dlg = ScaleDialog(src_w=800, src_h=400)   # 2:1
    qtbot.addWidget(dlg)
    assert dlg.lock_aspect.isChecked()
    dlg.spin_w.setValue(400)
    # 비율 유지면 높이는 절반(200) 이어야.
    assert dlg.spin_h.value() == 200
    assert dlg.target_size() == (400, 200)


def test_dialog_unlocked_aspect_does_not_propagate(qtbot):
    dlg = ScaleDialog(src_w=800, src_h=400)
    qtbot.addWidget(dlg)
    dlg.lock_aspect.setChecked(False)
    dlg.spin_w.setValue(200)
    # 잠금 해제 — 높이는 그대로
    assert dlg.spin_h.value() == 400
    assert dlg.target_size() == (200, 400)


def test_dialog_percent_mode(qtbot):
    dlg = ScaleDialog(src_w=200, src_h=100)
    qtbot.addWidget(dlg)
    dlg.mode_percent.setChecked(True)
    dlg.spin_pct.setValue(150)
    w, h = dlg.target_size()
    assert w == 300 and h == 150


def test_dialog_pixel_to_percent_mode_sync(qtbot):
    dlg = ScaleDialog(src_w=400, src_h=200)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(800)   # 200%
    dlg.mode_percent.setChecked(True)
    # 모드 전환 시 픽셀 입력값을 퍼센트로 동기화해 미리보기가 끊기지 않게.
    assert dlg.spin_pct.value() == 200
    assert dlg.target_size() == (800, 400)


def test_dialog_preview_label_reflects_current_input(qtbot):
    dlg = ScaleDialog(src_w=100, src_h=100)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(50)
    assert "50" in dlg.preview_label.text()
    assert "다운스케일" in dlg.preview_label.text()
    dlg.spin_w.setValue(200)
    assert "업스케일" in dlg.preview_label.text()
