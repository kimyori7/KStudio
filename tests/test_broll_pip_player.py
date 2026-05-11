"""BrollPipPlayer 단위 + 통합 테스트.

BrollPipPlayer 는 QObject (QWidget 아님) — qtbot.addWidget 불가.
qapp fixture 로 QApplication 만 보장하고 인스턴스는 로컬 scope 로 cleanup.

ffmpeg 가 PATH 에 있을 때만 실제 mp4 fixture 로 frame_ready 통합 검증.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from screen_recorder.effects import Sidecar, Trim
from screen_recorder.effects.types.broll import BrollEffect, PipConfig
from screen_recorder.ui.video.broll_pip_player import BrollPipPlayer


@pytest.fixture
def ffmpeg_or_skip():
    """ffmpeg 가 PATH 에 없으면 skip — 통합 테스트만 영향."""
    p = shutil.which("ffmpeg")
    if p is None:
        pytest.skip("ffmpeg not on PATH")
    return p


@pytest.fixture
def black_mp4(tmp_path, ffmpeg_or_skip):
    """1 초 검은 화면 fixture (160x120, libx264, faststart)."""
    out = tmp_path / "black.mp4"
    subprocess.run(
        [ffmpeg_or_skip, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-t", "1", str(out)],
        check=True,
    )
    return out


def _sidecar_with_broll(in_ms: int, out_ms: int, src: str) -> Sidecar:
    eff = BrollEffect(
        in_ms=in_ms, out_ms=out_ms, src=src,
        placement="pip", pip=PipConfig(corner="bottom-right", size_ratio=0.3),
    )
    return Sidecar(
        source_path="x.mp4",
        source_hash="h",
        trim=Trim(in_ms=0, out_ms=10000),
        effects=[eff],
    )


def test_pip_player_starts_idle(qapp):
    p = BrollPipPlayer()
    assert p.active_effect_id() is None
    assert p.loaded_src() is None
    p.deleteLater()


def test_activate_sets_active_id_and_loads_src(qapp, tmp_path):
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    assert p.active_effect_id() == "eff-1"
    assert p.loaded_src() == str(dummy)
    p.deleteLater()


def test_deactivate_clears_active(qapp, tmp_path):
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    p.deactivate()
    assert p.active_effect_id() is None
    p.deleteLater()


def test_activate_same_src_no_reload(qapp, tmp_path):
    """같은 src 로 재activate 시 setSource 재호출 안 함 (eff_id 만 갱신)."""
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    src1 = p.loaded_src()
    p.activate(str(dummy), "eff-2")   # same src, different effect
    assert p.loaded_src() == src1
    assert p.active_effect_id() == "eff-2"
    p.deleteLater()


def test_set_playing_mirrors_intent(qapp, tmp_path):
    """set_playing(True/False) 가 wrapper 의 is_playing() 의도와 매칭."""
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    p.set_playing(True)
    assert p.is_playing() is True
    p.set_playing(False)
    assert p.is_playing() is False
    p.deleteLater()


def test_set_speed_records_rate(qapp, tmp_path):
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    p.set_speed(2.0)
    assert abs(p.current_speed() - 2.0) < 1e-3
    p.deleteLater()


def test_seek_to_records_last_ms(qapp, tmp_path):
    """seek_to(broll_local_ms) 가 player.setPosition 호출 + 기록."""
    p = BrollPipPlayer()
    dummy = tmp_path / "a.mp4"
    dummy.write_bytes(b"")
    p.activate(str(dummy), "eff-1")
    p.seek_to(500)
    assert p.last_seek_ms() == 500
    p.deleteLater()


def test_position_inside_window_activates(qapp, tmp_path):
    """combined position 이 in_ms ~ out_ms 안이면 activate 호출."""
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(dummy)))
    p.on_combined_position_changed(3000)
    assert p.active_effect_id() is not None
    assert p.loaded_src() == str(dummy)
    p.deleteLater()


def test_position_outside_window_deactivates(qapp, tmp_path):
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(dummy)))
    p.on_combined_position_changed(3000)
    p.on_combined_position_changed(5000)   # out of window
    assert p.active_effect_id() is None
    p.deleteLater()


def test_position_inside_window_seeks_relative(qapp, tmp_path):
    """진입 직후 seek_to(combined - in_ms). combined 3000, in_ms 2000 → broll 1000ms."""
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(dummy)))
    p.on_combined_position_changed(3000)
    assert p.last_seek_ms() == 1000
    p.deleteLater()


def test_drift_within_threshold_no_reseek(qapp, tmp_path, monkeypatch):
    """PIP position 이 expected (combined - in_ms) 근처면 재시크 안 함.

    expected=1100ms, fake position=1080ms → drift 20ms < 300ms → 진입 시점의
    seek (1000) 가 마지막 그대로.
    """
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(dummy)))
    p.on_combined_position_changed(3000)   # 진입, seek_to(1000)
    monkeypatch.setattr(p._player, "position", lambda: 1080)
    p.on_combined_position_changed(3100)
    assert p.last_seek_ms() == 1000
    p.deleteLater()


def test_drift_over_threshold_reseeks_on_user_jump(qapp, tmp_path, monkeypatch):
    """사용자 슬라이더 jump — combined 가 갑자기 크게 변하면 PIP position 과
    expected 차이가 커져 재시크.
    """
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(dummy)))
    p.on_combined_position_changed(3000)   # 진입, seek_to(1000)
    monkeypatch.setattr(p._player, "position", lambda: 1000)
    p.on_combined_position_changed(3500)   # expected 1500 vs actual 1000 → drift 500
    assert p.last_seek_ms() == 1500
    p.deleteLater()


def test_drift_over_threshold_reseeks_on_decoder_lag(qapp, tmp_path, monkeypatch):
    """자연 재생 중 PIP 디코더가 뒤처져 누적 drift — 재시크로 재동기.

    spec 의 핵심 시나리오: 30초 broll 동안 PIP 가 500ms 뒤처지면 보정 필요.
    """
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 32_000, str(dummy)))
    p.on_combined_position_changed(3000)   # 진입, seek_to(1000)
    # 30초 후 자연 재생 진행. combined 도 30초 흘렀지만 PIP position 은 lag.
    monkeypatch.setattr(p._player, "position", lambda: 28_500)   # 500ms 뒤처짐
    p.on_combined_position_changed(31_000)   # expected 29_000 vs actual 28_500
    assert p.last_seek_ms() == 29_000
    p.deleteLater()


def test_image_src_broll_not_activated(qapp, tmp_path):
    """src 가 이미지 (.png/.jpg) 면 BrollPipPlayer 가 활성화 안 함 — thumbnail fallback."""
    p = BrollPipPlayer()
    img = tmp_path / "still.png"
    img.write_bytes(b"")
    p.set_sidecar(_sidecar_with_broll(2000, 4000, str(img)))
    p.on_combined_position_changed(3000)
    assert p.active_effect_id() is None
    p.deleteLater()


def test_frame_ready_emits_after_activate_and_play(qtbot, black_mp4):
    """실제 mp4 로 activate + play → frame_ready 가 도착해야 한다.

    ffmpeg fixture 가 있을 때만 동작 (없으면 skip). 통합 회귀 게이트.
    """
    p = BrollPipPlayer()
    received: list = []
    p.frame_ready.connect(lambda eff_id, img: received.append((eff_id, img)))
    p.activate(str(black_mp4), "eff-1")
    p.set_playing(True)
    qtbot.waitUntil(lambda: len(received) > 0, timeout=5000)
    eff_id, img = received[0]
    assert eff_id == "eff-1"
    assert not img.isNull()
    p.deactivate()
    p.deleteLater()


def test_set_sidecar_clears_stale_active(qapp, tmp_path):
    """기존 활성 broll 이 새 사이드카에 없으면 deactivate."""
    p = BrollPipPlayer()
    dummy = tmp_path / "b.mp4"
    dummy.write_bytes(b"")
    sc = _sidecar_with_broll(2000, 4000, str(dummy))
    p.set_sidecar(sc)
    p.on_combined_position_changed(3000)
    assert p.active_effect_id() is not None
    # 새 사이드카 — broll 자체 제거.
    empty = Sidecar(
        source_path="x.mp4", source_hash="h",
        trim=Trim(in_ms=0, out_ms=10000), effects=[],
    )
    p.set_sidecar(empty)
    assert p.active_effect_id() is None
    p.deleteLater()
