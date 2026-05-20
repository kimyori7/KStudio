"""SubtitleExportDialog — 폼 ↔ SubtitleExportSettings 양방향."""
from __future__ import annotations

import pytest

from screen_recorder.ui.subtitle_export_dialog import SubtitleExportSettingsDialog


@pytest.fixture
def dlg(qtbot):
    d = SubtitleExportSettingsDialog()
    qtbot.addWidget(d)
    return d


def test_defaults_match_user_request(dlg):
    """사용자 명시 — TXT 디폴트, Whisper base 모델."""
    s = dlg.current_settings()
    assert s.format == "txt"
    assert s.model_size == "base"


def test_select_srt_reflects(dlg):
    dlg.srt_radio.setChecked(True)
    assert dlg.current_settings().format == "srt"


def test_select_back_to_txt(dlg):
    dlg.srt_radio.setChecked(True)
    dlg.txt_radio.setChecked(True)
    assert dlg.current_settings().format == "txt"


def test_change_whisper_model(dlg):
    """드롭다운에서 large-v3 선택 → settings 반영."""
    dlg.model_combo.setCurrentText("large-v3")
    assert dlg.current_settings().model_size == "large-v3"


def test_model_combo_has_all_sizes(dlg):
    """5개 모델 모두 콤보에 노출."""
    items = [dlg.model_combo.itemText(i) for i in range(dlg.model_combo.count())]
    for size in ("tiny", "base", "small", "medium", "large-v3"):
        assert size in items, f"missing model: {size}"


def test_initial_model_can_be_passed(qtbot):
    """다이얼로그 생성 시 초기 모델 지정 가능 — settings 기본값 일치."""
    d = SubtitleExportSettingsDialog(initial_model="medium")
    qtbot.addWidget(d)
    assert d.current_settings().model_size == "medium"


def test_suggested_extension_matches_format(dlg):
    assert dlg.suggested_extension() == ".txt"
    dlg.srt_radio.setChecked(True)
    assert dlg.suggested_extension() == ".srt"
