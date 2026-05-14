"""의존성 누락 시 해당 카드 dim + tooltip."""
from unittest.mock import patch
from screen_recorder.autoedit.result import AutoEditResult
from screen_recorder.ui.autoedit.review_dialog import AutoEditReviewDialog


def test_scenedetect_missing_dims_scene_card(qtbot):
    raw = AutoEditResult(source_hash="x")
    with patch("screen_recorder.ui.autoedit.review_dialog._is_scenedetect_available", return_value=False):
        d = AutoEditReviewDialog(raw)
        qtbot.addWidget(d)
        assert not d.scene_checkbox().isEnabled()
        assert "pip install scenedetect" in d.scene_checkbox().toolTip()


def test_librosa_missing_dims_bpm_card(qtbot):
    raw = AutoEditResult(source_hash="x")
    with patch("screen_recorder.ui.autoedit.review_dialog._is_librosa_available", return_value=False):
        d = AutoEditReviewDialog(raw)
        qtbot.addWidget(d)
        assert not d.bpm_checkbox().isEnabled()
        assert "pip install librosa" in d.bpm_checkbox().toolTip()
