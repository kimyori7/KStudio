"""이미지 업/다운스케일 (scale.py + ScaleDialog + upscale.py) 테스트."""
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


# ---------- ScaleDialog AI 옵션 ----------

def test_dialog_ai_checkbox_default_unchecked(qtbot):
    dlg = ScaleDialog(src_w=100, src_h=100)
    qtbot.addWidget(dlg)
    assert not dlg.use_ai.isChecked()
    assert not dlg.wants_ai_upscale()


def test_dialog_ai_disabled_for_same_size(qtbot):
    """기본 진입은 동일 크기 — AI 옵션 비활성 (의미 없음)."""
    dlg = ScaleDialog(src_w=200, src_h=100)
    qtbot.addWidget(dlg)
    assert not dlg.use_ai.isEnabled()


def test_dialog_ai_disabled_for_downscale(qtbot):
    dlg = ScaleDialog(src_w=400, src_h=200)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(200)   # 다운스케일
    assert not dlg.use_ai.isEnabled()
    assert not dlg.wants_ai_upscale()


def test_dialog_ai_enabled_for_upscale(qtbot):
    dlg = ScaleDialog(src_w=200, src_h=100)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(800)   # 업스케일
    assert dlg.use_ai.isEnabled()


def test_dialog_ai_auto_unchecks_on_downscale_transition(qtbot):
    """업스케일에서 AI 켜둔 상태 → 다운스케일로 바뀌면 자동 해제."""
    dlg = ScaleDialog(src_w=200, src_h=100)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(800)
    assert dlg.use_ai.isEnabled()
    dlg.use_ai.setChecked(True)
    assert dlg.wants_ai_upscale()
    # 다운스케일로 이동
    dlg.spin_w.setValue(100)
    assert not dlg.use_ai.isEnabled()
    assert not dlg.use_ai.isChecked()


def test_dialog_wants_ai_upscale_only_when_enabled_and_checked(qtbot):
    dlg = ScaleDialog(src_w=200, src_h=100)
    qtbot.addWidget(dlg)
    dlg.spin_w.setValue(800)
    dlg.use_ai.setChecked(True)
    assert dlg.wants_ai_upscale()
    dlg.use_ai.setChecked(False)
    assert not dlg.wants_ai_upscale()


# ---------- upscale.py — 모델 레지스트리 / 캐시 ----------

def test_upscale_default_model_id_in_registry():
    from screen_recorder.encode import upscale
    info = upscale.model_info(upscale.DEFAULT_MODEL_ID)
    assert info["scale"] == 4
    assert info["filename"].endswith(".onnx")
    assert info["url"].startswith("https://")


def test_upscale_cache_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KSTUDIO_REALESRGAN_HOME", str(tmp_path))
    from screen_recorder.encode import upscale
    assert upscale.cache_dir() == tmp_path


def test_upscale_is_model_downloaded_false_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("KSTUDIO_REALESRGAN_HOME", str(tmp_path))
    from screen_recorder.encode import upscale
    assert not upscale.is_model_downloaded(upscale.DEFAULT_MODEL_ID)


def test_upscale_is_model_downloaded_true_when_file_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("KSTUDIO_REALESRGAN_HOME", str(tmp_path))
    from screen_recorder.encode import upscale
    info = upscale.model_info(upscale.DEFAULT_MODEL_ID)
    p = tmp_path / info["filename"]
    p.write_bytes(b"x" * 100)
    assert upscale.is_model_downloaded(upscale.DEFAULT_MODEL_ID)


def test_upscale_model_info_raises_for_unknown():
    from screen_recorder.encode import upscale
    with pytest.raises(ValueError):
        upscale.model_info("nonexistent_model")


# ---------- upscale.py — 추론 (mocked InferenceSession) ----------

class _FakeInput:
    def __init__(self, name="input"):
        self.name = name


class _FakeSession:
    """4x 업스케일을 흉내내는 가짜 ONNX 세션. 입력 [1,3,h,w] → 출력 [1,3,4h,4w]."""

    def __init__(self, scale=4):
        self._scale = scale
        self.run_calls: list[tuple[int, int]] = []   # (h, w) per call

    def get_inputs(self):
        return [_FakeInput()]

    def run(self, _outputs, feed):
        import numpy as np
        x = next(iter(feed.values()))   # [1, 3, h, w]
        n, c, h, w = x.shape
        self.run_calls.append((h, w))
        # 단순한 nearest 4배 — 픽셀 그대로 4*4 블록으로 복제
        out = np.repeat(np.repeat(x, self._scale, axis=2), self._scale, axis=3)
        return [out]


def test_upscale_qimage_returns_4x_dimensions():
    """가짜 세션을 주입해 추론 흐름이 정확한 크기를 만드는지."""
    from screen_recorder.encode import upscale
    src = QImage(64, 32, QImage.Format_ARGB32)
    src.fill(0xFFAABBCC)
    session = _FakeSession(scale=4)
    out = upscale.upscale_qimage(
        src,
        upscale.DEFAULT_MODEL_ID,
        tile_size=64,
        tile_pad=8,
        session_factory=lambda _p: session,
    )
    assert out.width() == 64 * 4
    assert out.height() == 32 * 4


def test_upscale_qimage_invokes_progress_callback():
    from screen_recorder.encode import upscale
    src = QImage(64, 64, QImage.Format_ARGB32)
    src.fill(0xFF000000)
    session = _FakeSession(scale=4)
    progress: list[tuple[int, int]] = []
    upscale.upscale_qimage(
        src,
        upscale.DEFAULT_MODEL_ID,
        tile_size=32,   # 64/32 = 2x2 = 4 tiles
        tile_pad=4,
        session_factory=lambda _p: session,
        progress_cb=lambda d, t: progress.append((d, t)),
    )
    assert len(progress) == 4
    # 마지막 호출은 (4, 4)
    assert progress[-1] == (4, 4)


def test_upscale_qimage_does_not_mutate_input():
    from screen_recorder.encode import upscale
    src = QImage(48, 48, QImage.Format_ARGB32)
    src.fill(0xFF112233)
    session = _FakeSession(scale=4)
    _ = upscale.upscale_qimage(
        src, upscale.DEFAULT_MODEL_ID,
        tile_size=32, tile_pad=4,
        session_factory=lambda _p: session,
    )
    assert src.width() == 48 and src.height() == 48


def test_upscale_qimage_uses_padding_in_tile_request():
    """경계 타일은 양쪽 패딩이 들어가 입력 크기가 step 보다 커야 한다."""
    from screen_recorder.encode import upscale
    src = QImage(128, 64, QImage.Format_ARGB32)
    src.fill(0xFF888888)
    session = _FakeSession(scale=4)
    upscale.upscale_qimage(
        src, upscale.DEFAULT_MODEL_ID,
        tile_size=64, tile_pad=8,
        session_factory=lambda _p: session,
    )
    # 가운데 타일은 양쪽 8px 패딩 = 80 너비, 가장자리는 한쪽만 = 72 너비.
    # 모든 호출이 64 보다 크거나 같아야 한다.
    assert all(h >= 64 and w >= 64 for h, w in session.run_calls)
    # 적어도 한 호출은 패딩 덕분에 64 보다 커야 한다.
    assert any(h > 64 or w > 64 for h, w in session.run_calls)
