"""EditController 의 효과 단위 API — add/update/remove."""
from pathlib import Path

import pytest

from screen_recorder.effects.types.caption import CaptionEffect
from screen_recorder.ui.video.edit_controller import EditController


@pytest.fixture
def video(tmp_path: Path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x" * 200_000)
    return p


def test_add_effect_pushes_history_and_updates_sidecar(qtbot, video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    ec.set_edit_mode(True)
    cap = CaptionEffect(in_ms=1000, out_ms=4000, text="안녕")

    with qtbot.waitSignal(ec.sidecar_replaced, timeout=1000):
        ec.add_effect(cap)

    assert len(ec.sidecar().effects) == 1
    assert ec.sidecar().effects[0].id == cap.id


def test_update_effect_replaces_by_id(qtbot, video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    cap = CaptionEffect(in_ms=1000, out_ms=4000, text="hi")
    ec.add_effect(cap)
    cap_v2 = CaptionEffect(id=cap.id, in_ms=1000, out_ms=4000, text="bye")

    ec.update_effect(cap_v2)

    assert len(ec.sidecar().effects) == 1
    assert ec.sidecar().effects[0].text == "bye"


def test_update_effect_unknown_id_no_op(video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    other = CaptionEffect(id="not-there", in_ms=0, out_ms=1000, text="x")
    ec.update_effect(other)
    assert ec.sidecar().effects == []


def test_remove_effect_by_id(qtbot, video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    cap = CaptionEffect(in_ms=1000, out_ms=4000, text="hi")
    ec.add_effect(cap)
    ec.remove_effect(cap.id)
    assert ec.sidecar().effects == []


def test_remove_effect_unknown_id_no_op(video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    ec.remove_effect("not-there")
    assert ec.sidecar().effects == []


def test_add_effect_rejects_overlap_same_type(video, tmp_path):
    """같은 type 의 시간 겹치는 효과 추가 시도 → 거부 (False 반환)."""
    ec = EditController(video, tmp_path / "sidecars")
    a = CaptionEffect(in_ms=0, out_ms=2000, text="a")
    ec.add_effect(a)
    b = CaptionEffect(in_ms=1000, out_ms=3000, text="b")  # overlaps a
    ok = ec.add_effect(b)
    assert ok is False
    assert len(ec.sidecar().effects) == 1


def test_undo_after_add_effect_restores_empty(qtbot, video, tmp_path):
    ec = EditController(video, tmp_path / "sidecars")
    ec.add_effect(CaptionEffect(in_ms=0, out_ms=1000, text="x"))
    ec.undo()
    assert ec.sidecar().effects == []
