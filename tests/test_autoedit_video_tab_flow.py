"""VideoTab — 🪄 버튼 클릭 → coordinator.run() → 다이얼로그 → 적용 시 sidecar 갱신."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys
from screen_recorder.autoedit.result import AutoEditResult
from screen_recorder.ui.video_tab import VideoTab


def test_autoedit_button_click_runs_coordinator(qtbot, tmp_path: Path):
    media = tmp_path / "v.mp4"
    media.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000)
    tab = VideoTab(
        path=media, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)

    # coordinator.run 을 mock — 실제 Whisper 호출 차단. result 즉시 emit.
    fake_raw = AutoEditResult(source_hash="abc", silence_segments=[(0, 2000)])
    with patch.object(tab.autoedit_coordinator(), "run",
                      side_effect=lambda **kw: tab.autoedit_coordinator().result_ready.emit(fake_raw, [])):
        # 다이얼로그 전체를 mock — modal exec() 가 프로세스를 block 하지 않도록.
        # QDialog.Rejected(0) 을 반환해 '적용' 경로 미진입.
        mock_dlg = MagicMock()
        mock_dlg.exec.return_value = 0  # QDialog.Rejected
        mock_dlg.Accepted = 1
        with patch("screen_recorder.ui.autoedit.review_dialog.AutoEditReviewDialog",
                   return_value=mock_dlg):
            tab.autoedit_button().click()

    # 마지막 raw 가 저장됐는지 (다이얼로그 표시 path 검증).
    assert tab._autoedit_last_raw is fake_raw


def test_autoedit_accepted_branch_uses_qdialog_enum(qtbot, tmp_path: Path):
    """Accepted 비교가 QDialog.DialogCode.Accepted 로 안전한지 — instance 접근 안 함.

    회귀 (2026-05-14): `dlg.exec() == dlg.Accepted` 가 PySide6 에서 AttributeError.
    인스턴스 통해 enum 접근 안 됨. 다이얼로그 표시 직후 crash 시킴.
    """
    from PySide6.QtWidgets import QDialog
    media = tmp_path / "v.mp4"
    media.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000)
    tab = VideoTab(
        path=media, source_label="v", duration_ms=10_000,
        player_settings=PlayerSettings(), player_hotkeys=PlayerHotkeys(),
        sidecar_dir=tmp_path / "sidecars",
    )
    qtbot.addWidget(tab)

    # Accepted 분기 진입 검증 — compute_effects 실제 호출되는지.
    fake_raw = AutoEditResult(source_hash="abc", silence_segments=[(0, 2000)])
    accepted_dlg = MagicMock()
    accepted_dlg.exec.return_value = QDialog.DialogCode.Accepted
    accepted_dlg.compute_effects.return_value = []   # 비어도 OK — path 만 검증

    with patch.object(tab.autoedit_coordinator(), "run",
                      side_effect=lambda **kw: tab.autoedit_coordinator().result_ready.emit(fake_raw, [])):
        with patch("screen_recorder.ui.autoedit.review_dialog.AutoEditReviewDialog",
                   return_value=accepted_dlg):
            tab.autoedit_button().click()

    # Accepted 분기 도달했으면 compute_effects 호출됨.
    accepted_dlg.compute_effects.assert_called_once()
