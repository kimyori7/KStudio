"""EditController.update_trim — 사이드카 trim 영구 저장."""
from __future__ import annotations
from pathlib import Path

import pytest

from screen_recorder.effects import Sidecar
from screen_recorder.ui.video.edit_controller import EditController


@pytest.fixture
def sample_mp4(tmp_path):
    p = tmp_path / "sample.mp4"
    p.write_bytes(b"\x00" * 1000)
    return p


@pytest.fixture
def ctrl(qtbot, sample_mp4, tmp_path):
    return EditController(sample_mp4, tmp_path / "sidecars")


def test_update_trim_persists_to_sidecar(ctrl):
    ctrl.update_trim(in_ms=500, out_ms=4_500)
    assert ctrl.sidecar().trim.in_ms == 500
    assert ctrl.sidecar().trim.out_ms == 4_500


def test_update_trim_emits_sidecar_replaced(ctrl, qtbot):
    with qtbot.waitSignal(ctrl.sidecar_replaced, timeout=500):
        ctrl.update_trim(in_ms=200, out_ms=1_000)


def test_update_trim_pushes_history(ctrl):
    ctrl.update_trim(in_ms=100, out_ms=900)
    ctrl.update_trim(in_ms=200, out_ms=1_000)
    ctrl.undo()
    assert ctrl.sidecar().trim.in_ms == 100
    assert ctrl.sidecar().trim.out_ms == 900


def test_update_trim_zero_zero_is_no_trim(ctrl):
    """둘 다 0 = 트림 없음 (Sidecar.trim 의 default)."""
    ctrl.update_trim(in_ms=500, out_ms=4_500)
    assert ctrl.sidecar().trim.in_ms == 500
    ctrl.update_trim(in_ms=0, out_ms=0)
    assert ctrl.sidecar().trim.in_ms == 0
    assert ctrl.sidecar().trim.out_ms == 0
