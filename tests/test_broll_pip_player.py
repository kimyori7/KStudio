"""BrollPipPlayer 단위 + 통합 테스트.

BrollPipPlayer 는 QObject (QWidget 아님) — qtbot.addWidget 불가.
qapp fixture 로 QApplication 만 보장하고 인스턴스는 로컬 scope 로 cleanup.
"""
from __future__ import annotations

import pytest

from screen_recorder.ui.video.broll_pip_player import BrollPipPlayer


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
