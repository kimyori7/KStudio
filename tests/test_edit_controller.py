"""EditController 단위 테스트 — set_audio_muted 등."""
from __future__ import annotations


# ============================================================
# set_audio_muted
# ============================================================
def test_set_audio_muted_toggles_and_is_idempotent(tmp_path):
    from screen_recorder.ui.video.edit_controller import EditController

    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 4096)
    ctrl = EditController(video, tmp_path)

    assert ctrl.sidecar().audio_muted is False

    # False → True: 실제 변경 → True 반환.
    assert ctrl.set_audio_muted(True) is True
    assert ctrl.sidecar().audio_muted is True

    # 같은 값 재호출 — no-op → False 반환.
    assert ctrl.set_audio_muted(True) is False
    assert ctrl.sidecar().audio_muted is True  # 값 불변
